"""
Voice Type - Hold Shift to speak, release to type.
Uses Groq Whisper API for fast, accurate speech-to-text.
"""

import sys
import os
import threading
import time
import json
import tempfile
import re
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(line_buffering=True)
if sys.stderr:
    sys.stderr.reconfigure(line_buffering=True)

print("Loading Voice Type...")

import keyboard
import pyperclip
import tkinter as tk
from tkinter import font as tkfont, ttk
import pyaudio
import wave
import httpx
import pystray
from PIL import Image, ImageDraw

print("Ready!")

# Config
CONFIG_FILE = Path.home() / ".voice-type-config.json"
SAMPLE_RATE = 16000

# Default filter words - common filler words the model outputs when nothing is said
DEFAULT_FILTER_WORDS = ["thank you", "thanks", "thank you.", "thanks."]

# Load config
config_data = {
    "api_key": "",
    "mic_index": None,
    "hotkey": "shift",
    "accounting_mode": False,
    "filter_words": DEFAULT_FILTER_WORDS
}
if CONFIG_FILE.exists():
    try:
        config_data = json.loads(CONFIG_FILE.read_text())
    except:
        pass

# Also try old config file for backward compatibility
old_config = Path.home() / "voice-type-config.txt"
if not config_data.get("api_key") and old_config.exists():
    config_data["api_key"] = old_config.read_text().strip()

API_KEY = config_data.get("api_key", "")
MIC_INDEX = config_data.get("mic_index")
HOTKEY = config_data.get("hotkey", "shift")
ACCOUNTING_MODE = config_data.get("accounting_mode", False)
ACCOUNTING_COMMA = config_data.get("accounting_comma", False)
CASUAL_MODE = config_data.get("casual_mode", False)
FILTER_WORDS = config_data.get("filter_words", DEFAULT_FILTER_WORDS)

# Debug: Show config on startup
print(f"[startup] Config file: {CONFIG_FILE}")
print(f"[startup] ACCOUNTING_MODE from config: {ACCOUNTING_MODE}")
print(f"[startup] Full config: {config_data}")


# State
class State:
    recording = False
    running = True


state = State()
settings_open = False
tray_icon = None


class FloatingWidget:
    """Floating window to show status with modern design."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        # Show in taskbar - this makes it behave like a normal app
        self.root.attributes("-toolwindow", False)

        # Modern color scheme - dark mode
        self.bg_dark = "#1a1a2e"
        self.bg_medium = "#16213e"
        self.bg_light = "#0f3460"
        self.accent_primary = "#4a9eff"
        self.accent_secondary = "#533483"
        self.accent_success = "#00ff88"
        self.accent_warning = "#ffc107"
        self.text_primary = "#ffffff"
        self.text_secondary = "#a0a0a0"
        self.border_color = "#4a9eff"

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        # Widget dimensions
        widget_width = 320
        widget_height = 100
        
        # Center horizontally, near bottom
        x = (screen_width - widget_width) // 2
        y = screen_height - widget_height - 100
        self.root.geometry(f"{widget_width}x{widget_height}+{x}+{y}")

        self.root.configure(bg=self.bg_dark)

        # Main frame with border
        self.main_frame = tk.Frame(
            self.root, 
            bg=self.bg_dark,
            highlightbackground=self.border_color,
            highlightthickness=2
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Content frame
        self.content_frame = tk.Frame(self.main_frame, bg=self.bg_medium)
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # Status indicator row
        self.status_frame = tk.Frame(self.content_frame, bg=self.bg_medium)
        self.status_frame.pack(fill=tk.X, padx=15, pady=(12, 5))

        # Status icon/label
        self.status_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.status_label = tk.Label(
            self.status_frame,
            text="● Ready",
            font=self.status_font,
            fg=self.accent_success,
            bg=self.bg_medium,
        )
        self.status_label.pack(side=tk.LEFT)

        # Recording indicator (hidden by default)
        self.rec_indicator = tk.Label(
            self.status_frame,
            text="",
            font=("Segoe UI", 10),
            fg=self.accent_primary,
            bg=self.bg_medium,
        )
        self.rec_indicator.pack(side=tk.RIGHT)

        # Separator line
        self.separator = tk.Frame(self.content_frame, height=1, bg=self.border_color)
        self.separator.pack(fill=tk.X, padx=15, pady=8)

        # Text display
        self.text_font = tkfont.Font(family="Segoe UI", size=11)
        self.text_label = tk.Label(
            self.content_frame,
            text="Hold Shift to speak...",
            font=self.text_font,
            fg=self.text_secondary,
            bg=self.bg_medium,
            wraplength=280,
        )
        self.text_label.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 12))

        # Status colors
        self.colors = {
            "ready": (self.accent_success, "● Ready"),
            "recording": (self.accent_primary, "● Recording"),
            "processing": (self.accent_warning, "◐ Transcribing"),
            "done": (self.accent_success, "✓ Done"),
            "error": (self.accent_primary, "✕ Error"),
            "nokey": (self.accent_primary, "✕ No API Key"),
        }

        # Drag functionality
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.content_frame.bind("<Button-1>", self.start_drag)
        self.content_frame.bind("<B1-Motion>", self.drag)
        self.status_label.bind("<Button-1>", self.start_drag)
        self.status_label.bind("<B1-Motion>", self.drag)
        self.text_label.bind("<Button-1>", self.start_drag)
        self.text_label.bind("<B1-Motion>", self.drag)

        # Start hidden
        self.hidden = True
        self.root.withdraw()

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")

    def hide_widget(self):
        self.hidden = True
        self.root.withdraw()

    def show_widget(self):
        self.hidden = False
        self.root.deiconify()

    def open_settings(self):
        global settings_open
        if settings_open:
            return
        settings_open = True

        win = tk.Toplevel()
        win.title("Voice Type Settings")
        win.geometry("500x700")
        win.configure(bg=self.bg_dark)
        win.resizable(False, False)

        # Header
        header_frame = tk.Frame(win, bg=self.bg_medium, height=50)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        tk.Label(
            header_frame, 
            text="⚙ Voice Type Settings", 
            font=("Segoe UI", 14, "bold"),
            fg=self.border_color,
            bg=self.bg_medium
        ).pack(pady=12)

        # Separator
        tk.Frame(win, height=2, bg=self.border_color).pack(fill=tk.X)

        # Content frame
        content = tk.Frame(win, bg=self.bg_dark)
        content.pack(fill=tk.BOTH, expand=True, padx=25, pady=15)

        # Style for inputs
        input_style = {
            "bg": self.bg_light,
            "fg": self.text_primary,
            "insertbackground": self.text_primary,
            "relief": "flat",
            "font": ("Segoe UI", 10)
        }
        
        label_style = {
            "bg": self.bg_dark,
            "fg": self.text_secondary,
            "font": ("Segoe UI", 10)
        }

        # API Key Section
        tk.Label(content, text="🔐 API Key", font=("Segoe UI", 11, "bold"), 
                fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        tk.Label(content, text="Groq API Key:", **label_style).pack(anchor="w")
        
        api_entry = tk.Entry(content, width=50, **input_style)
        api_entry.pack(fill=tk.X, pady=(5, 15))
        api_entry.insert(0, API_KEY)

        # Microphone Section
        tk.Label(content, text="🎤 Microphone", font=("Segoe UI", 11, "bold"),
                fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        tk.Label(content, text="Select input device:", **label_style).pack(anchor="w")

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Settings.TCombobox", 
                       fieldbackground=self.bg_light, 
                       background=self.bg_light, 
                       foreground=self.text_primary,
                       arrowcolor=self.border_color,
                       borderwidth=0)
        style.map("Settings.TCombobox",
                 fieldbackground=[('readonly', self.bg_light)],
                 selectbackground=[('readonly', self.border_color)],
                 selectforeground=[('readonly', self.bg_dark)])
        
        mic_combo = ttk.Combobox(content, width=47, style="Settings.TCombobox", font=("Segoe UI", 10))
        mic_combo.pack(fill=tk.X, pady=(5, 15))

        # Get mics
        p = pyaudio.PyAudio()
        mics = []
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev["maxInputChannels"] > 0:
                mics.append((i, dev["name"]))
        p.terminate()

        mic_combo["values"] = [f"{i}: {n}" for i, n in mics]

        if MIC_INDEX is not None:
            for idx, (i, n) in enumerate(mics):
                if i == MIC_INDEX:
                    mic_combo.current(idx)
                    break
        elif mics:
            mic_combo.current(0)

        # Hotkey Section
        tk.Label(content, text="⌨ Push-to-Talk Key", font=("Segoe UI", 11, "bold"),
                fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        
        hotkey_frame = tk.Frame(content, bg=self.bg_dark)
        hotkey_frame.pack(fill=tk.X, pady=(5, 15))

        hotkey_var = tk.StringVar(value=HOTKEY.upper())
        hotkey_entry = tk.Entry(
            hotkey_frame, 
            width=10,
            bg=self.bg_light,
            fg=self.border_color,
            insertbackground=self.border_color,
            textvariable=hotkey_var,
            font=("Segoe UI", 12, "bold"),
            justify="center",
            relief="flat"
        )
        hotkey_entry.pack(side=tk.LEFT)
        hotkey_entry.config(state="readonly")
        
        def on_hotkey_focus(event):
            hotkey_entry.config(state="normal")
            hotkey_var.set("...")
            hotkey_entry.config(state="readonly")
        
        def on_hotkey_keypress(event):
            key_name = None
            special_keys = {
                16: "shift", 17: "ctrl", 18: "alt",
                32: "space",
                112: "f1", 113: "f2", 114: "f3", 115: "f4",
                116: "f5", 117: "f6", 118: "f7", 119: "f8",
                120: "f9", 121: "f10", 122: "f11", 123: "f12",
            }
            
            if event.keycode in special_keys:
                key_name = special_keys[event.keycode]
            elif event.keysym and len(event.keysym) == 1:
                key_name = event.keysym.lower()
            elif event.keysym:
                key_name = event.keysym.lower()
            
            if key_name:
                hotkey_entry.config(state="normal")
                hotkey_var.set(key_name.upper())
                hotkey_entry.config(state="readonly")
            return "break"
        
        hotkey_entry.bind("<FocusIn>", on_hotkey_focus)
        hotkey_entry.bind("<KeyPress>", on_hotkey_keypress)

        tk.Label(hotkey_frame, text="  (click and press a key)", 
                bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # Features Section
        tk.Label(content, text="✨ Features", font=("Segoe UI", 11, "bold"),
                fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        
        accounting_var = tk.BooleanVar(value=ACCOUNTING_MODE)
        accounting_check = tk.Checkbutton(
            content,
            text="🔢 Accounting Mode (convert words like 'one' to '1')",
            variable=accounting_var,
            bg=self.bg_dark,
            fg=self.text_primary,
            selectcolor=self.bg_light,
            activebackground=self.bg_dark,
            activeforeground=self.text_primary,
            font=("Segoe UI", 10),
            cursor="hand2"
        )
        accounting_check.pack(anchor="w", pady=(5, 5))
        
        # Accounting comma formatting option
        comma_var = tk.BooleanVar(value=ACCOUNTING_COMMA)
        comma_check = tk.Checkbutton(
            content,
            text="   └─ Add commas to large numbers (e.g., '1,234,567')",
            variable=comma_var,
            bg=self.bg_dark,
            fg=self.text_secondary,
            selectcolor=self.bg_light,
            activebackground=self.bg_dark,
            activeforeground=self.text_primary,
            font=("Segoe UI", 9),
            cursor="hand2"
        )
        comma_check.pack(anchor="w", pady=(0, 5))
        
        # Casual mode option
        casual_var = tk.BooleanVar(value=CASUAL_MODE)
        casual_check = tk.Checkbutton(
            content,
            text="💬 Casual Mode (lowercase, no formal punctuation)",
            variable=casual_var,
            bg=self.bg_dark,
            fg=self.text_primary,
            selectcolor=self.bg_light,
            activebackground=self.bg_dark,
            activeforeground=self.text_primary,
            font=("Segoe UI", 10),
            cursor="hand2"
        )
        casual_check.pack(anchor="w", pady=(5, 15))

        # Filter Words
        tk.Label(content, text="🚫 Filter Words", font=("Segoe UI", 11, "bold"),
                fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        tk.Label(content, text="Phrases to block (comma-separated):", **label_style).pack(anchor="w")

        filter_entry = tk.Entry(content, width=50, **input_style)
        filter_entry.pack(fill=tk.X, pady=(5, 5))
        filter_entry.insert(0, ", ".join(FILTER_WORDS) if FILTER_WORDS else "")
        
        tk.Label(content, text="Example: thank you, thanks", 
                bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 15))

        # Buttons
        btn_frame = tk.Frame(content, bg=self.bg_dark)
        btn_frame.pack(pady=20)

        def save():
            global API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE, FILTER_WORDS
            API_KEY = api_entry.get().strip()
            idx = mic_combo.current()
            if idx >= 0 and mics:
                MIC_INDEX = mics[idx][0]
            
            new_hotkey = hotkey_var.get().lower()
            if new_hotkey and new_hotkey != "...":
                HOTKEY = new_hotkey

            ACCOUNTING_MODE = accounting_var.get()
            ACCOUNTING_COMMA = comma_var.get()
            CASUAL_MODE = casual_var.get()
            
            filter_text_val = filter_entry.get().strip()
            if filter_text_val:
                FILTER_WORDS = [w.strip() for w in filter_text_val.split(",") if w.strip()]
            else:
                FILTER_WORDS = []

            config_data["api_key"] = API_KEY
            config_data["mic_index"] = MIC_INDEX
            config_data["hotkey"] = HOTKEY
            config_data["accounting_mode"] = ACCOUNTING_MODE
            config_data["accounting_comma"] = ACCOUNTING_COMMA
            config_data["casual_mode"] = CASUAL_MODE
            config_data["filter_words"] = FILTER_WORDS
            CONFIG_FILE.write_text(json.dumps(config_data))

            if tray_icon:
                tray_icon.title = f"Voice Type (Hold {HOTKEY.upper()})"

            save_btn.config(text="✓ Saved!", bg=self.accent_success)
            win.after(1500, lambda: save_btn.config(text="Save", bg=self.border_color))

        def get_key():
            import webbrowser
            webbrowser.open("https://console.groq.com/keys")

        def close_settings():
            global settings_open
            settings_open = False
            win.destroy()

        btn_style = {
            "font": ("Segoe UI", 10, "bold"),
            "relief": "flat",
            "cursor": "hand2",
            "width": 12,
            "height": 1
        }
        
        save_btn = tk.Button(btn_frame, text="Save", bg=self.border_color, fg="white",
                            command=save, **btn_style)
        save_btn.pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="Get API Key", bg=self.accent_secondary, fg="white",
                 command=get_key, **btn_style).pack(side=tk.LEFT, padx=5)
        
        tk.Button(btn_frame, text="Close", bg=self.bg_light, fg=self.text_primary,
                 command=close_settings, **btn_style).pack(side=tk.LEFT, padx=5)

        def on_close():
            global settings_open
            settings_open = False
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

    def quit_app(self):
        state.running = False
        keyboard.unhook_all()
        if tray_icon:
            tray_icon.stop()
        self.root.quit()
        os._exit(0)

    def update_status(self, status_key, text=""):
        color, status_text = self.colors.get(status_key, self.colors["ready"])
        display = f"{status_text} {text}" if text else status_text
        self.status_label.configure(text=display, fg=color)
        if text and status_key == "done":
            self.text_label.configure(text=text, fg="#f8f8f2")
        elif status_key == "recording":
            self.text_label.configure(text="Speak now...", fg="#f8f8f2")
        elif status_key == "processing":
            self.text_label.configure(text="Transcribing...", fg="#f8f8f2")

    def run(self):
        self.root.mainloop()


widget = None


def update_status(status_key, text=""):
    if widget:
        widget.root.after(0, lambda: widget.update_status(status_key, text))


def create_tray_icon():
    """Create system tray icon."""
    # Create a simple microphone icon
    width = 64
    height = 64
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)

    # Draw microphone shape
    dc.ellipse([20, 8, 44, 36], fill="#50fa7b", outline="#50fa7b")
    dc.rectangle([28, 36, 36, 48], fill="#50fa7b")
    dc.arc([12, 32, 52, 56], 0, 180, fill="#50fa7b", width=3)
    dc.line([32, 52, 32, 60], fill="#50fa7b", width=3)
    dc.line([22, 60, 42, 60], fill="#50fa7b", width=3)

    def on_settings(icon, item):
        widget.root.after(0, widget.open_settings)

    def on_show(icon, item):
        widget.root.after(0, widget.show_widget)

    def on_quit(icon, item):
        widget.root.after(0, widget.quit_app)

    menu = pystray.Menu(
        pystray.MenuItem("Settings", on_settings),
        pystray.MenuItem("Show Widget", on_show),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    return pystray.Icon("voice_type", image, f"Voice Type (Hold {HOTKEY.upper()})", menu)


def transcribe_with_groq(audio_path):
    """Use Groq Whisper API for transcription."""
    global API_KEY

    if not API_KEY:
        return None, "No API key"

    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {API_KEY}"}

        with open(audio_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": "whisper-large-v3-turbo", "response_format": "json"}

            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            return result.get("text"), None
        else:
            return None, f"HTTP {response.status_code}"

    except Exception as e:
        return None, str(e)


# Emoji mapping for voice commands
EMOJI_MAP = {
    # Common emotions
    "happy emoji": "😊", "smile emoji": "😊", "smiling emoji": "😊",
    "sad emoji": "😢", "crying emoji": "😭", "tears emoji": "😭",
    "angry emoji": "😠", "mad emoji": "😠", "frustrated emoji": "😤",
    "laughing emoji": "😂", "lol emoji": "😂", "haha emoji": "😂",
    "love emoji": "❤️", "heart emoji": "❤️", "hearts emoji": "💕",
    "cool emoji": "😎", "sunglasses emoji": "😎",
    "wink emoji": "😉", "winking emoji": "😉",
    "surprised emoji": "😲", "shocked emoji": "😱",
    "thinking emoji": "🤔", "hmm emoji": "🤔",
    "sleepy emoji": "😴", "tired emoji": "😴",
    "sick emoji": "🤒", "ill emoji": "🤒",
    "nerd emoji": "🤓", "geek emoji": "🤓",
    
    # Reactions
    "thumbs up emoji": "👍", "thumbs down emoji": "👎",
    "ok emoji": "👌", "okay emoji": "👌",
    "clap emoji": "👏", "applause emoji": "👏",
    "fire emoji": "🔥", "hot emoji": "🔥", "lit emoji": "🔥",
    "star emoji": "⭐", "stars emoji": "✨",
    "party emoji": "🎉", "celebration emoji": "🎉", "confetti emoji": "🎊",
    "boom emoji": "💥", "explosion emoji": "💥",
    "check emoji": "✅", "checkmark emoji": "✅", "done emoji": "✅",
    "x emoji": "❌", "cross emoji": "❌", "no emoji": "❌",
    "question emoji": "❓", "confused emoji": "❓",
    "exclamation emoji": "❗", "warning emoji": "⚠️",
    "idea emoji": "💡", "lightbulb emoji": "💡", "bulb emoji": "💡",
    
    # Hands/Gestures
    "wave emoji": "👋", "hello emoji": "👋", "hi emoji": "👋",
    "peace emoji": "✌️", "victory emoji": "✌️",
    "fist emoji": "👊", "punch emoji": "👊",
    "fingers crossed emoji": "🤞", "good luck emoji": "🤞",
    "pray emoji": "🙏", "please emoji": "🙏", "thanks emoji": "🙏",
    "high five emoji": "🙌", "raise hands emoji": "🙌",
    "shrug emoji": "🤷", "idk emoji": "🤷",
    "facepalm emoji": "🤦",
    
    # Animals
    "dog emoji": "🐕", "puppy emoji": "🐶",
    "cat emoji": "🐱", "kitty emoji": "🐱",
    "monkey emoji": "🐵", "see no evil emoji": "🙈",
    "fox emoji": "🦊",
    "bear emoji": "🐻",
    "panda emoji": "🐼",
    "unicorn emoji": "🦄",
    "butterfly emoji": "🦋",
    "snake emoji": "🐍",
    
    # Food & Drinks
    "pizza emoji": "🍕",
    "burger emoji": "🍔", "hamburger emoji": "🍔",
    "coffee emoji": "☕", "latte emoji": "☕",
    "beer emoji": "🍺",
    "wine emoji": "🍷",
    "cake emoji": "🎂", "birthday emoji": "🎂",
    "ice cream emoji": "🍦",
    
    # Weather & Nature
    "sun emoji": "☀️", "sunny emoji": "☀️",
    "moon emoji": "🌙", "crescent moon emoji": "🌙",
    "cloud emoji": "☁️", "cloudy emoji": "☁️",
    "rain emoji": "🌧️", "rainy emoji": "🌧️",
    "snow emoji": "❄️", "snowflake emoji": "❄️",
    "rainbow emoji": "🌈",
    "flower emoji": "🌸", "blossom emoji": "🌸",
    "tree emoji": "🌳",
    
    # Objects & Symbols
    "rocket emoji": "🚀", "launch emoji": "🚀",
    "computer emoji": "💻", "laptop emoji": "💻",
    "phone emoji": "📱", "mobile emoji": "📱",
    "email emoji": "📧", "mail emoji": "📧",
    "book emoji": "📖",
    "pencil emoji": "✏️", "write emoji": "✏️",
    "lock emoji": "🔒", "secure emoji": "🔒",
    "key emoji": "🔑", "password emoji": "🔑",
    "clock emoji": "⏰", "alarm emoji": "⏰",
    "calendar emoji": "📅", "date emoji": "📅",
    "money emoji": "💰", "cash emoji": "💰", "dollar emoji": "💵",
    "gift emoji": "🎁", "present emoji": "🎁",
    "camera emoji": "📷", "photo emoji": "📷",
    
    # People & Activities
    "runner emoji": "🏃", "running emoji": "🏃",
    "dancer emoji": "💃", "dancing emoji": "💃",
    "coder emoji": "👨‍💻", "developer emoji": "👨‍💻", "programmer emoji": "👨‍💻",
    "artist emoji": "🎨", "paint emoji": "🎨",
    "gamer emoji": "🎮", "gaming emoji": "🎮", "video game emoji": "🎮",
    "music emoji": "🎵", "song emoji": "🎵", "note emoji": "🎵",
    "microphone emoji": "🎤", "mic emoji": "🎤",
    "movie emoji": "🎬", "film emoji": "🎬", "cinema emoji": "🎬",
    "workout emoji": "💪", "muscle emoji": "💪", "strong emoji": "💪",
    
    # Flags & Places
    "usa emoji": "🇺🇸", "america emoji": "🇺🇸", "us flag emoji": "🇺🇸",
    "uk emoji": "🇬🇧", "britain emoji": "🇬🇧", "england emoji": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "world emoji": "🌍", "globe emoji": "🌍", "earth emoji": "🌍",
    
    # Common phrases
    "100 emoji": "💯",
    "rock emoji": "🪨",
    "rock and roll emoji": "🤘", "metal emoji": "🤘",
    "skull emoji": "💀", "dead emoji": "💀",
    "ghost emoji": "👻",
    "alien emoji": "👽",
    "robot emoji": "🤖", "bot emoji": "🤖",
    "poop emoji": "💩", "shit emoji": "💩",
    "egg emoji": "🥚", "easter emoji": "🥚",
    "eye emoji": "👁️", "eyes emoji": "👀",
    "ear emoji": "👂",
    "nose emoji": "👃",
}


def convert_emojis(text):
    """Convert emoji phrases to actual emojis."""
    result = text
    
    # Sort by length (longest first) to avoid partial matches
    sorted_emojis = sorted(EMOJI_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    
    for phrase, emoji in sorted_emojis:
        # Case-insensitive replacement
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        result = pattern.sub(emoji, result)
    
    # Clean up any double spaces left after replacements
    result = re.sub(r'\s+', ' ', result).strip()
    
    return result


# Number word to digit mapping for accounting mode
# Only use unambiguous number words to avoid false positives
NUMBER_WORD_MAP = {
    # Basic numbers 0-9
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    
    # Teens
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    
    # Tens
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fourty": "40",
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
}


def convert_numbers_to_digits(text):
    """Convert number words to digits for accounting mode."""
    result = text
    
    # Sort by length (longest first) to avoid partial matches
    sorted_numbers = sorted(NUMBER_WORD_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    
    for word, digit in sorted_numbers:
        # Match word boundaries including punctuation
        # This handles "one, two, three" properly
        pattern = re.compile(
            r'(?<![a-zA-Z])' + re.escape(word) + r'(?![a-zA-Z])',
            re.IGNORECASE
        )
        result = pattern.sub(digit, result)
    
    return result


# Common Whisper hallucinations when no speech is detected
HALLUCINATION_PHRASES = [
    "thank you",
    "thanks", 
    "thank you.",
    "thanks.",
    "thank you for watching",
    "thanks for watching",
    "you",
    "you.",
    "bye",
    "bye.",
    "goodbye",
    "goodbye.",
    "subtitle",
    "subtitles",
    "caption",
    "captions",
]


def filter_text(text):
    """Filter out unwanted words from transcription."""
    global FILTER_WORDS
    
    if not text:
        return ""
    
    result = text.strip()
    
    # If empty after stripping, return empty
    if not result:
        return ""
    
    # Only use user's custom filter words - NOT hardcoded hallucinations
    # User has full control over what to filter
    if not FILTER_WORDS:
        return result
    
    # Check if the entire text matches a filter word (case-insensitive)
    result_lower = result.lower()
    for filter_word in FILTER_WORDS:
        filter_word_lower = filter_word.lower().strip()
        if result_lower == filter_word_lower:
            print(f"[filtered] Matched filter: '{filter_word}'")
            return ""
    
    # Also check if text contains filter word as substring (for short texts)
    if len(result) < 30:
        for filter_word in FILTER_WORDS:
            filter_word_lower = filter_word.lower().strip()
            if filter_word_lower in result_lower:
                print(f"[filtered] Contains filter: '{filter_word}'")
                return ""
    
    return result


def normalize_numbers_from_api(text):
    """Remove commas from numbers in API response unless comma mode is enabled."""
    global ACCOUNTING_COMMA
    
    print(f"[NORMALIZE] ACCOUNTING_COMMA = {ACCOUNTING_COMMA}")
    
    if ACCOUNTING_COMMA:
        # Comma mode is ON - keep commas as they are from API
        print(f"[NORMALIZE] Keeping commas (comma mode ON)")
        return text
    
    # Comma mode is OFF - remove commas from numbers
    # This handles cases where Groq API returns "1,234,567"
    def remove_commas(match):
        return match.group(0).replace(',', '')
    
    result = re.sub(r'\b[\d,]+\b', remove_commas, text)
    print(f"[NORMALIZE] Removed commas: '{text}' -> '{result}'")
    return result


def format_number_with_commas(text):
    """Add commas to large numbers in text if accounting comma mode is enabled."""
    global ACCOUNTING_COMMA
    
    print(f"[COMMA_FUNC] ACCOUNTING_COMMA value: {ACCOUNTING_COMMA}")
    
    # Explicit check - must be True to add commas
    if ACCOUNTING_COMMA is not True:
        print(f"[COMMA_FUNC] SKIPPING commas - mode is OFF")
        return text
    
    def add_commas(match):
        num = match.group(0)
        # Add commas every 3 digits from the right
        if len(num) > 3:
            return "{:,}".format(int(num))
        return num
    
    # Find all numbers with 4+ digits and add commas
    print(f"[COMMA_FUNC] ADDING commas")
    return re.sub(r'\b\d{4,}\b', add_commas, text)


def apply_casual_mode(text):
    """Apply casual formatting: lowercase and informal punctuation."""
    global CASUAL_MODE
    
    if not CASUAL_MODE:
        return text
    
    print(f"[CASUAL] Applying casual mode to: '{text}'")
    
    # Convert to lowercase
    result = text.lower()
    
    # Replace formal punctuation with casual equivalents
    # Remove periods at end of sentences (casual texting style)
    result = re.sub(r'\.$', '', result)
    result = re.sub(r'\.(\s)', r'\1', result)
    
    # Keep exclamation and question marks as they add emotion
    # But remove multiple punctuation like "!!!" or "???" down to one
    result = re.sub(r'[!]{2,}', '!', result)
    result = re.sub(r'[?]{2,}', '?', result)
    
    # Remove formal commas that aren't needed for clarity
    # Keep commas in numbers though
    result = re.sub(r',\s+', ' ', result)
    
    print(f"[CASUAL] Result: '{result}'")
    return result


def type_text(text):
    """Type text using clipboard."""
    global ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE
    
    # Very explicit debug
    print("=" * 60)
    print(f"[TYPE_TEXT] ACCOUNTING_MODE = {ACCOUNTING_MODE}")
    print(f"[TYPE_TEXT] ACCOUNTING_COMMA = {ACCOUNTING_COMMA}")
    print(f"[TYPE_TEXT] Original text: '{text}'")
    
    # First, normalize numbers from API (remove commas unless comma mode is ON)
    text = normalize_numbers_from_api(text)
    
    # Then convert number words to digits if accounting mode is enabled
    # Do this BEFORE filtering so "one" -> "1" works
    if ACCOUNTING_MODE:
        original = text
        text = convert_numbers_to_digits(text)
        print(f"[TYPE_TEXT] CONVERTED: '{original}' -> '{text}'")
        
        # Add commas to large numbers if enabled
        if ACCOUNTING_COMMA:
            text_before_comma = text
            text = format_number_with_commas(text)
            if text != text_before_comma:
                print(f"[TYPE_TEXT] COMMAS: '{text_before_comma}' -> '{text}'")
    else:
        print(f"[TYPE_TEXT] SKIPPING conversion - mode is OFF")
    print("=" * 60)
    
    # Apply filter after conversion
    text = filter_text(text)
    
    # If text was filtered out, don't type anything
    if not text:
        print("[filtered] Text was filtered out, nothing to type")
        return
    
    # Convert emoji phrases to actual emojis
    text = convert_emojis(text)
    
    # Apply casual mode (lowercase, informal punctuation)
    text = apply_casual_mode(text)
    
    print(f"[typing] {text}")
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.press_and_release("ctrl+v")


def record_and_transcribe():
    """Record audio while Shift is held, then transcribe with Groq Whisper."""
    # Show widget when recording starts
    if widget and widget.hidden:
        widget.root.after(0, widget.show_widget)
    update_status("recording", "Speak now...")
    print("Recording...")

    try:
        mic_idx = MIC_INDEX if MIC_INDEX is not None else 0

        p = pyaudio.PyAudio()

        chunk = 1024
        format = pyaudio.paInt16
        channels = 1
        rate = SAMPLE_RATE

        stream = p.open(
            format=format,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=mic_idx,
            frames_per_buffer=chunk,
        )

        frames = []
        start_time = time.time()

        while keyboard.is_pressed(HOTKEY):
            data = stream.read(chunk, exception_on_overflow=False)
            frames.append(data)

        duration = time.time() - start_time
        print(f"Recorded {duration:.1f}s")

        stream.stop_stream()
        stream.close()
        p.terminate()

        if len(frames) < 15:
            update_status("error", "Too short")
            time.sleep(1)
            widget.root.after(0, widget.hide_widget)
            state.recording = False
            return

        if not API_KEY:
            update_status("nokey", "Open Settings")
            time.sleep(2)
            widget.root.after(0, widget.hide_widget)
            state.recording = False
            return

        update_status("processing", "")

        # Save to temp wav
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wf = wave.open(temp_path, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(format))
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
        wf.close()

        # Transcribe
        text, error = transcribe_with_groq(temp_path)
        Path(temp_path).unlink(missing_ok=True)

        if text:
            text = text.strip()
            print(f"[whisper] {text}")
            update_status("done", text)
            type_text(text)

            def hide_after_done():
                time.sleep(2)
                if widget:
                    widget.root.after(0, widget.hide_widget)

            threading.Thread(target=hide_after_done, daemon=True).start()
        else:
            update_status("error", error or "Failed")

            def hide_after_error():
                time.sleep(2)
                if widget:
                    widget.root.after(0, widget.hide_widget)

            threading.Thread(target=hide_after_error, daemon=True).start()

    except Exception as e:
        update_status("error", str(e)[:30])
        print(f"Error: {e}")
        time.sleep(1.5)
        widget.root.after(0, widget.hide_widget)
    finally:
        state.recording = False


def hotkey_loop():
    """Poll for hotkey state."""
    was_pressed = False
    while state.running:
        is_pressed = keyboard.is_pressed(HOTKEY)
        if is_pressed and not was_pressed and not state.recording:
            was_pressed = True
            state.recording = True
            threading.Thread(target=record_and_transcribe, daemon=True).start()
        elif not is_pressed and was_pressed:
            was_pressed = False
        time.sleep(0.02)


def main():
    global widget, tray_icon

    print("=" * 50)
    print(f"Voice Type - Groq Whisper (Hold {HOTKEY.upper()})")
    print("=" * 50)

    if not API_KEY:
        print("\n  No API key found!")
        print("Get free key: https://console.groq.com/keys")
    else:
        print(f"API key loaded ({len(API_KEY)} chars)")

    widget = FloatingWidget()

    # Create and start tray icon
    tray_icon = create_tray_icon()
    threading.Thread(target=tray_icon.run, daemon=True).start()

    threading.Thread(target=hotkey_loop, daemon=True).start()

    print(f"\nReady! Hold {HOTKEY.upper()} to record.")

    # Auto-open settings window on startup
    widget.root.after(500, widget.open_settings)

    try:
        widget.run()
    except KeyboardInterrupt:
        widget.quit_app()


if __name__ == "__main__":
    main()
