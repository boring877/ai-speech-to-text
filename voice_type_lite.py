"""
Voice Type Lite - Optimized for older computers.
Uses Groq Whisper API for fast, accurate speech-to-text.
"""

import sys
import threading
import time
import tempfile
import re
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(line_buffering=True)

print("Loading Voice Type Lite...")

import keyboard
import pyperclip
import tkinter as tk
import pyaudio
import wave
import webbrowser

from modules.core import (
    CONFIG_FILE, SAMPLE_RATE, DEFAULT_FILTER_WORDS,
    load_config, save_config,
    transcribe_with_groq as _transcribe_core,
    convert_numbers_to_digits,
    filter_text as _filter_text_core,
    apply_casual_mode as _apply_casual_mode_core,
)

print("Ready!")

# Load config
config_data = load_config()

API_KEY = config_data.get("api_key", "")
MIC_INDEX = config_data.get("mic_index")
HOTKEY = config_data.get("hotkey", "shift")
ACCOUNTING_MODE = config_data.get("accounting_mode", False)
ACCOUNTING_COMMA = config_data.get("accounting_comma", False)
CASUAL_MODE = config_data.get("casual_mode", False)
FILTER_WORDS = config_data.get("filter_words", DEFAULT_FILTER_WORDS)
THEME = config_data.get("theme", "dark")

print(f"[startup] HOTKEY: {HOTKEY}")
print(f"[startup] MIC_INDEX: {MIC_INDEX}")

# State
recording = False
running = True
settings_open = False


class FloatingWidget:
    """Simple floating window - optimized for older computers."""

    def _get_colors(self, theme):
        if theme == "light":
            return {
                "bg_main":           "#f0f0f0",
                "bg_frame":          "#ffffff",
                "border":            "#4a9eff",
                "fg_hint":           "#555555",
                "status_ready":      "#28a745",
                "status_recording":  "#1a73e8",
                "status_processing": "#e07b00",
                "status_done":       "#28a745",
                "status_error":      "#dc3545",
                "win_bg":            "#f0f0f0",
                "lbl_fg":            "#1a1a1a",
                "input_bg":          "#e0e0e0",
                "input_fg":          "#1a1a1a",
                "check_select":      "#e0e0e0",
            }
        else:
            return {
                "bg_main":           "#1a1a2e",
                "bg_frame":          "#16213e",
                "border":            "#4a9eff",
                "fg_hint":           "#a0a0a0",
                "status_ready":      "#00ff88",
                "status_recording":  "#4a9eff",
                "status_processing": "#ffc107",
                "status_done":       "#00ff88",
                "status_error":      "#ff5555",
                "win_bg":            "#2d2d44",
                "lbl_fg":            "white",
                "input_bg":          "#3d3d5c",
                "input_fg":          "white",
                "check_select":      "#3d3d5c",
            }

    def __init__(self):
        self.colors = self._get_colors(THEME)
        c = self.colors

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()

        widget_width = 320
        widget_height = 100

        x = (screen_width - widget_width) // 2
        y = screen_height - widget_height - 80
        self.root.geometry(f"{widget_width}x{widget_height}+{x}+{y}")
        self.root.configure(bg=c["bg_main"])

        self.frame = tk.Frame(self.root, bg=c["bg_frame"], highlightbackground=c["border"], highlightthickness=1)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.status_label = tk.Label(
            self.frame,
            text="Ready",
            font=("Arial", 11),
            fg=c["status_ready"],
            bg=c["bg_frame"]
        )
        self.status_label.pack(pady=(8, 2))

        self.text_label = tk.Label(
            self.frame,
            text=f"Hold {HOTKEY.upper()} to speak...",
            font=("Arial", 10),
            fg=c["fg_hint"],
            bg=c["bg_frame"],
            wraplength=300,
            justify="center",
        )
        self.text_label.pack(pady=(0, 6))

        self.hidden = True
        self.root.withdraw()

        # Handle window close button - quit app entirely
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def apply_theme(self, theme):
        """Re-color all floating-window widgets when theme changes."""
        self.colors = self._get_colors(theme)
        c = self.colors
        self.root.configure(bg=c["bg_main"])
        self.frame.configure(bg=c["bg_frame"], highlightbackground=c["border"])
        self.status_label.configure(bg=c["bg_frame"])
        self.text_label.configure(fg=c["fg_hint"], bg=c["bg_frame"], wraplength=300)

    def hide_widget(self):
        self.hidden = True
        self.root.withdraw()

    def show_widget(self):
        self.hidden = False
        self.root.deiconify()

    def open_settings(self):
        global settings_open, API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE, FILTER_WORDS, THEME, config_data
        if settings_open:
            return
        settings_open = True

        c = self.colors

        win = tk.Toplevel()
        win.title("Voice Type Lite Settings")
        win.geometry("500x660")
        win.configure(bg=c["win_bg"])
        win.resizable(False, False)

        tk.Label(win, text="⚙ Voice Type Lite Settings", font=("Arial", 16, "bold"),
                fg="#4a9eff", bg=c["win_bg"]).pack(pady=15)

        content = tk.Frame(win, bg=c["win_bg"])
        content.pack(fill=tk.BOTH, expand=True, padx=25, pady=10)

        # API Key
        tk.Label(content, text="Groq API Key:", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w")
        api_entry = tk.Entry(content, width=55, bg=c["input_bg"], fg=c["input_fg"],
                            insertbackground=c["input_fg"], font=("Arial", 10), relief="flat")
        api_entry.pack(fill=tk.X, pady=(5, 15), ipady=5)
        api_entry.insert(0, API_KEY)

        # Microphone
        tk.Label(content, text="Microphone:", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w")

        mic_frame = tk.Frame(content, bg=c["win_bg"])
        mic_frame.pack(fill=tk.X, pady=(5, 15))

        p = pyaudio.PyAudio()
        mics = []
        mic_names = []
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev["maxInputChannels"] > 0:
                mics.append((i, dev["name"]))
                mic_names.append(f"{i}: {dev['name'][:35]}")
        p.terminate()

        mic_var = tk.StringVar()
        if mics:
            if MIC_INDEX is not None:
                for idx, (i, n) in enumerate(mics):
                    if i == MIC_INDEX:
                        mic_var.set(mic_names[idx])
                        break
            if not mic_var.get() and mic_names:
                mic_var.set(mic_names[0])

        mic_menu = tk.OptionMenu(mic_frame, mic_var, *mic_names)
        mic_menu.config(bg=c["input_bg"], fg=c["input_fg"], font=("Arial", 10), width=48, relief="flat")
        mic_menu.pack(fill=tk.X, ipady=3)

        # Hotkey
        tk.Label(content, text="Push-to-Talk Key:", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w", pady=(10, 0))

        hotkey_frame = tk.Frame(content, bg=c["win_bg"])
        hotkey_frame.pack(fill=tk.X, pady=(5, 15))

        hotkey_var = tk.StringVar(value=HOTKEY.upper())
        hotkey_entry = tk.Entry(hotkey_frame, width=8, bg=c["input_bg"], fg="#4a9eff",
                               textvariable=hotkey_var, font=("Arial", 14, "bold"),
                               justify="center", relief="flat")
        hotkey_entry.pack(side=tk.LEFT, ipady=5)
        hotkey_entry.config(state="readonly")

        tk.Label(hotkey_frame, text="  (click and press a key)",
                bg=c["win_bg"], fg=c["fg_hint"], font=("Arial", 9)).pack(side=tk.LEFT)

        def on_key_press(event):
            key = event.keysym.lower() if event.keysym else None
            if key and key not in ("shift", "control", "alt", "win"):
                hotkey_entry.config(state="normal")
                hotkey_var.set(key.upper())
                hotkey_entry.config(state="readonly")
            return "break"

        def on_click(event):
            hotkey_entry.config(state="normal")
            hotkey_var.set("...")
            hotkey_entry.config(state="readonly")

        hotkey_entry.bind("<KeyPress>", on_key_press)
        hotkey_entry.bind("<Button-1>", on_click)

        # Theme
        tk.Label(content, text="Appearance:", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w", pady=(10, 5))
        theme_frame = tk.Frame(content, bg=c["win_bg"])
        theme_frame.pack(anchor="w")
        theme_var = tk.StringVar(value=THEME)
        for val, label in [("dark", "Dark"), ("light", "Light")]:
            tk.Radiobutton(theme_frame, text=label, variable=theme_var, value=val,
                          bg=c["win_bg"], fg=c["lbl_fg"], selectcolor=c["check_select"],
                          activebackground=c["win_bg"], font=("Arial", 10)).pack(side=tk.LEFT, padx=(0, 15))

        def on_theme_change(*args):
            new_theme = theme_var.get()
            self.apply_theme(new_theme)
            def do_reopen():
                global settings_open
                settings_open = False
                win.destroy()
                self.open_settings()
            win.after(0, do_reopen)

        theme_var.trace_add("write", on_theme_change)

        # Features
        tk.Label(content, text="Features:", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w", pady=(10, 5))

        accounting_var = tk.BooleanVar(value=ACCOUNTING_MODE)
        tk.Checkbutton(content, text="Accounting Mode (words to numbers)", variable=accounting_var,
                      bg=c["win_bg"], fg=c["lbl_fg"], selectcolor=c["check_select"],
                      activebackground=c["win_bg"], font=("Arial", 10)).pack(anchor="w")

        comma_var = tk.BooleanVar(value=ACCOUNTING_COMMA)
        tk.Checkbutton(content, text="Add commas to large numbers", variable=comma_var,
                      bg=c["win_bg"], fg=c["fg_hint"], selectcolor=c["check_select"],
                      activebackground=c["win_bg"], font=("Arial", 9)).pack(anchor="w")

        casual_var = tk.BooleanVar(value=CASUAL_MODE)
        tk.Checkbutton(content, text="Casual Mode (lowercase)", variable=casual_var,
                      bg=c["win_bg"], fg=c["lbl_fg"], selectcolor=c["check_select"],
                      activebackground=c["win_bg"], font=("Arial", 10)).pack(anchor="w", pady=(5, 0))

        # Filter
        tk.Label(content, text="Filter Words (comma-separated):", fg=c["lbl_fg"], bg=c["win_bg"],
                font=("Arial", 11)).pack(anchor="w", pady=(15, 0))
        filter_entry = tk.Entry(content, width=55, bg=c["input_bg"], fg=c["input_fg"],
                               insertbackground=c["input_fg"], font=("Arial", 10), relief="flat")
        filter_entry.pack(fill=tk.X, pady=(5, 5), ipady=5)
        filter_entry.insert(0, ", ".join(FILTER_WORDS) if FILTER_WORDS else "")

        # Buttons
        btn_frame = tk.Frame(content, bg=c["win_bg"])
        btn_frame.pack(pady=25)

        def save():
            global API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE, FILTER_WORDS, THEME, config_data

            old_theme = THEME

            API_KEY = api_entry.get().strip()

            selected = mic_var.get()
            for i, name in enumerate(mic_names):
                if name == selected and i < len(mics):
                    MIC_INDEX = mics[i][0]
                    print(f"[save] Mic: {MIC_INDEX}")
                    break

            new_hotkey = hotkey_var.get().lower()
            if new_hotkey and new_hotkey != "...":
                keyboard.unhook_all_hotkeys()
                HOTKEY = new_hotkey
                setup_hotkey()
                print(f"[save] Hotkey: {HOTKEY}")

            ACCOUNTING_MODE = accounting_var.get()
            ACCOUNTING_COMMA = comma_var.get()
            CASUAL_MODE = casual_var.get()

            filter_str = filter_entry.get().strip()
            FILTER_WORDS = [w.strip() for w in filter_str.split(",") if w.strip()] if filter_str else []

            THEME = theme_var.get()
            theme_changed = THEME != old_theme
            self.apply_theme(THEME)

            config_data["api_key"] = API_KEY
            config_data["mic_index"] = MIC_INDEX
            config_data["hotkey"] = HOTKEY
            config_data["accounting_mode"] = ACCOUNTING_MODE
            config_data["accounting_comma"] = ACCOUNTING_COMMA
            config_data["casual_mode"] = CASUAL_MODE
            config_data["filter_words"] = FILTER_WORDS
            config_data["theme"] = THEME

            try:
                save_config(config_data)
                print(f"[save] Saved to {CONFIG_FILE}")
                save_btn.config(text="✓ Saved!", bg="#00aa55")
            except Exception as e:
                print(f"[save] ERROR: {e}")
                save_btn.config(text="Error!", bg="#aa0000")

            if theme_changed:
                settings_open = False
                win.destroy()
                self.open_settings()
            else:
                win.after(1500, lambda: save_btn.config(text="Save", bg="#4a9eff"))

        def close():
            global settings_open
            settings_open = False
            win.destroy()

        def close_and_quit():
            """Close settings and quit the entire app."""
            global running
            running = False
            keyboard.unhook_all()
            win.destroy()
            self.root.quit()
            sys.exit(0)

        save_btn = tk.Button(btn_frame, text="Save", command=save, 
                            bg="#4a9eff", fg="white", font=("Arial", 11, "bold"), 
                            width=12, height=1, relief="raised", borderwidth=2, cursor="hand2")
        save_btn.pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Close", command=close_and_quit, 
                 bg="#555577", fg="white", font=("Arial", 11), 
                 width=12, height=1, relief="raised", borderwidth=2, cursor="hand2").pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Get API Key",
                 command=lambda: webbrowser.open("https://console.groq.com/keys"),
                 bg="#8855cc", fg="white", font=("Arial", 11), 
                 width=12, height=1, relief="raised", borderwidth=2, cursor="hand2").pack(side=tk.LEFT, padx=8)

        # When user clicks X on settings window, quit entire app
        win.protocol("WM_DELETE_WINDOW", close_and_quit)

    def quit_app(self):
        global running
        running = False
        keyboard.unhook_all()
        self.root.quit()
        sys.exit(0)

    def update_status(self, status, text=""):
        c = self.colors
        colors = {
            "ready":      c["status_ready"],
            "recording":  c["status_recording"],
            "processing": c["status_processing"],
            "done":       c["status_done"],
            "error":      c["status_error"],
            "nokey":      c["status_error"],
        }
        status_text = {"ready": "Ready", "recording": "Recording...", "processing": "Transcribing...",
                       "done": "Done", "error": "Error", "nokey": "No API Key"}

        self.status_label.configure(text=status_text.get(status, status), fg=colors.get(status, c["lbl_fg"]))
        if text:
            self.text_label.configure(text=text)

    def run(self):
        self.root.mainloop()


widget = None


def transcribe_with_groq(audio_path):
    """Use Groq Whisper API via core module."""
    return _transcribe_core(audio_path, API_KEY)


def convert_numbers(text):
    if not ACCOUNTING_MODE:
        return text
    return convert_numbers_to_digits(text)


def filter_text(text):
    return _filter_text_core(text, FILTER_WORDS)


def type_text(text):
    if not text:
        return
    
    if not ACCOUNTING_COMMA:
        text = re.sub(r'\b([\d]+),([\d]+)\b', r'\1\2', text)
    
    text = convert_numbers(text)
    text = filter_text(text)
    if not text:
        return
    
    if CASUAL_MODE:
        text = _apply_casual_mode_core(text)

    print(f"[typing] {text}")
    pyperclip.copy(text)
    time.sleep(0.03)
    keyboard.press_and_release("ctrl+v")


def record_and_transcribe():
    global recording
    
    if widget.hidden:
        widget.root.after(0, widget.show_widget)
    widget.update_status("recording")
    print("Recording...")

    try:
        mic_idx = MIC_INDEX if MIC_INDEX is not None else 0
        p = pyaudio.PyAudio()
        
        chunk = 512
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                       input=True, input_device_index=mic_idx, frames_per_buffer=chunk)

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

        if len(frames) < 10:
            widget.update_status("error", "Too short")
            time.sleep(1)
            widget.root.after(0, widget.hide_widget)
            recording = False
            return

        if not API_KEY:
            widget.update_status("nokey")
            time.sleep(2)
            widget.root.after(0, widget.hide_widget)
            recording = False
            return

        widget.update_status("processing")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wf = wave.open(temp_path, "wb")
        wf.setnchannels(1)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(frames))
        wf.close()

        text, error = transcribe_with_groq(temp_path)
        Path(temp_path).unlink(missing_ok=True)

        if text:
            text = text.strip()
            print(f"[whisper] {text}")
            word_count = len(text.split())
            widget.update_status("done", f"{text}  •  {word_count}w")
            type_text(text)
            time.sleep(2.5)
            widget.root.after(0, widget.hide_widget)
        else:
            widget.update_status("error", error or "Failed")
            time.sleep(2)
            widget.root.after(0, widget.hide_widget)

    except Exception as e:
        print(f"Error: {e}")
        widget.update_status("error", str(e)[:20])
        time.sleep(1.5)
        widget.root.after(0, widget.hide_widget)
    finally:
        recording = False


def on_hotkey_press():
    """Called when hotkey is pressed."""
    global recording
    if not recording:
        recording = True
        print(f"[hotkey] {HOTKEY} pressed, starting recording...")
        threading.Thread(target=record_and_transcribe, daemon=True).start()


def setup_hotkey():
    """Set up the hotkey hook."""
    print(f"[hotkey] Setting up hotkey: {HOTKEY}")
    keyboard.on_press_key(HOTKEY, lambda e: on_hotkey_press())


def main():
    global widget

    print("=" * 50)
    print(f"Voice Type Lite v1.2.0 (Hold {HOTKEY.upper()})")
    print("=" * 50)

    if not API_KEY:
        print("\nNo API key! Get free key: https://console.groq.com/keys")
    else:
        print(f"API key loaded")

    widget = FloatingWidget()
    
    # Set up hotkey
    setup_hotkey()
    
    print(f"\nReady! Hold {HOTKEY.upper()} to record.")

    # Auto-open settings
    widget.root.after(500, widget.open_settings)

    try:
        widget.run()
    except KeyboardInterrupt:
        widget.quit_app()


if __name__ == "__main__":
    main()