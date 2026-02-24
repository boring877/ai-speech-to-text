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

# Load config
config_data = {"api_key": "", "mic_index": None, "hotkey": "shift"}
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


# State
class State:
    recording = False
    running = True


state = State()
settings_open = False
tray_icon = None


class FloatingWidget:
    """Floating window to show status."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - 360
        y = screen_height - 160
        self.root.geometry(f"340x120+{x}+{y}")

        self.root.configure(bg="#1e1e2e")

        self.frame = tk.Frame(
            self.root, bg="#1e1e2e", highlightbackground="#3d3d5c", highlightthickness=2
        )
        self.frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Status
        self.status_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.status_label = tk.Label(
            self.frame,
            text="🎤 Recording...",
            font=self.status_font,
            fg="#ff5555",
            bg="#1e1e2e",
            pady=8,
        )
        self.status_label.pack(fill=tk.X)

        # Text
        self.text_font = tkfont.Font(family="Segoe UI", size=11)
        self.text_label = tk.Label(
            self.frame,
            text="Speak now...",
            font=self.text_font,
            fg="#f8f8f2",
            bg="#1e1e2e",
            wraplength=320,
            pady=5,
        )
        self.text_label.pack(fill=tk.BOTH, expand=True)

        # Colors
        self.colors = {
            "ready": ("#50fa7b", "🎤 Ready"),
            "recording": ("#ff5555", "🔴 Recording..."),
            "processing": ("#bd93f9", "⏳ Transcribing..."),
            "done": ("#50fa7b", "✅"),
            "error": ("#ff5555", "❌"),
            "nokey": ("#ff5555", "❌ No API Key"),
        }

        # Drag
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.frame.bind("<Button-1>", self.start_drag)
        self.frame.bind("<B1-Motion>", self.drag)
        self.status_label.bind("<Button-1>", self.start_drag)
        self.status_label.bind("<B1-Motion>", self.drag)

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
        win.geometry("400x320")
        win.configure(bg="#1e1e2e")
        win.resizable(False, False)

        # API Key
        tk.Label(
            win, text="Groq API Key:", bg="#1e1e2e", fg="#f8f8f2", font=("Segoe UI", 10)
        ).pack(pady=(20, 5))

        api_entry = tk.Entry(
            win, width=50, bg="#282a36", fg="#f8f8f2", insertbackground="#f8f8f2"
        )
        api_entry.pack(pady=5)
        api_entry.insert(0, API_KEY)

        # Microphone
        tk.Label(
            win, text="Microphone:", bg="#1e1e2e", fg="#f8f8f2", font=("Segoe UI", 10)
        ).pack(pady=(15, 5))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TCombobox", 
                       fieldbackground="#ffffff", 
                       background="#ffffff", 
                       foreground="#000000",
                       arrowcolor="#000000")
        style.map("TCombobox",
                 fieldbackground=[('readonly', '#ffffff')],
                 selectbackground=[('readonly', '#e0e0e0')],
                 selectforeground=[('readonly', '#000000')])
        
        mic_combo = ttk.Combobox(win, width=47, style="TCombobox")
        mic_combo.pack(pady=5)

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

        # Hotkey
        tk.Label(
            win, text="Push-to-Talk Key:", bg="#1e1e2e", fg="#f8f8f2", font=("Segoe UI", 10)
        ).pack(pady=(15, 5))

        hotkey_frame = tk.Frame(win, bg="#1e1e2e")
        hotkey_frame.pack(pady=5)

        hotkey_var = tk.StringVar(value=HOTKEY.upper())
        hotkey_entry = tk.Entry(
            hotkey_frame, 
            width=15, 
            bg="#ffffff", 
            fg="#000000", 
            insertbackground="#000000",
            textvariable=hotkey_var,
            font=("Segoe UI", 10),
            justify="center"
        )
        hotkey_entry.pack(side=tk.LEFT, padx=5)
        
        # Make entry readonly and focusable for key capture
        hotkey_entry.config(state="readonly")
        
        def on_hotkey_focus(event):
            hotkey_entry.config(state="normal")
            hotkey_var.set("Press a key...")
            hotkey_entry.config(state="readonly")
        
        def on_hotkey_keypress(event):
            # Map keycodes to key names
            key_name = None
            
            # Special keys mapping
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
            
            return "break"  # Prevent default handling
        
        hotkey_entry.bind("<FocusIn>", on_hotkey_focus)
        hotkey_entry.bind("<KeyPress>", on_hotkey_keypress)

        tk.Label(
            hotkey_frame, text="(Click & press a key)", bg="#1e1e2e", fg="#6272a4", font=("Segoe UI", 9)
        ).pack(side=tk.LEFT, padx=5)

        # Buttons
        btn_frame = tk.Frame(win, bg="#1e1e2e")
        btn_frame.pack(pady=20)

        def save():
            global API_KEY, MIC_INDEX, HOTKEY
            API_KEY = api_entry.get().strip()
            idx = mic_combo.current()
            if idx >= 0 and mics:
                MIC_INDEX = mics[idx][0]
            
            new_hotkey = hotkey_var.get().lower()
            if new_hotkey and new_hotkey != "press a key...":
                HOTKEY = new_hotkey

            config_data["api_key"] = API_KEY
            config_data["mic_index"] = MIC_INDEX
            config_data["hotkey"] = HOTKEY
            CONFIG_FILE.write_text(json.dumps(config_data))

            # Update tray icon tooltip
            if tray_icon:
                tray_icon.title = f"Voice Type (Hold {HOTKEY.upper()})"

            win.destroy()
            global settings_open
            settings_open = False

        def get_key():
            import webbrowser

            webbrowser.open("https://console.groq.com/keys")

        def cancel():
            global settings_open
            settings_open = False
            win.destroy()

        tk.Button(
            btn_frame, text="Save", bg="#50fa7b", fg="#1e1e2e", width=10, command=save
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Get API Key",
            bg="#6272a4",
            fg="#f8f8f2",
            width=12,
            command=get_key,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            btn_frame,
            text="Cancel",
            bg="#44475a",
            fg="#f8f8f2",
            width=10,
            command=cancel,
        ).pack(side=tk.LEFT, padx=5)

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


def type_text(text):
    """Type text using clipboard."""
    # Convert emoji phrases to actual emojis
    text = convert_emojis(text)
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
        print("Right-click tray icon -> Settings")
        print("Get free key: https://console.groq.com/keys")
    else:
        print(f"API key loaded ({len(API_KEY)} chars)")

    widget = FloatingWidget()

    # Create and start tray icon
    tray_icon = create_tray_icon()
    threading.Thread(target=tray_icon.run, daemon=True).start()

    threading.Thread(target=hotkey_loop, daemon=True).start()

    print(f"\nReady! Hold {HOTKEY.upper()} to record.")
    print("Right-click tray icon for settings.")

    try:
        widget.run()
    except KeyboardInterrupt:
        widget.quit_app()


if __name__ == "__main__":
    main()
