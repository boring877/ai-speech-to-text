"""
Voice Type Lite - Optimized for older computers.
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

print("Loading Voice Type Lite...")

import keyboard
import pyperclip
import tkinter as tk
import pyaudio
import wave
import httpx

print("Ready!")

# Config - uses same config as regular version for compatibility
CONFIG_FILE = Path.home() / ".voice-type-config.json"
SAMPLE_RATE = 16000

# Default filter words
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
        print(f"[config] Loaded from {CONFIG_FILE}")
    except Exception as e:
        print(f"[config] Error loading: {e}")

API_KEY = config_data.get("api_key", "")
MIC_INDEX = config_data.get("mic_index")
HOTKEY = config_data.get("hotkey", "shift")
ACCOUNTING_MODE = config_data.get("accounting_mode", False)
ACCOUNTING_COMMA = config_data.get("accounting_comma", False)
CASUAL_MODE = config_data.get("casual_mode", False)
FILTER_WORDS = config_data.get("filter_words", DEFAULT_FILTER_WORDS)

print(f"[startup] HOTKEY: {HOTKEY}")
print(f"[startup] MIC_INDEX: {MIC_INDEX}")

# State
recording = False
running = True
settings_open = False


class FloatingWidget:
    """Simple floating window - optimized for older computers."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        widget_width = 280
        widget_height = 70
        
        x = (screen_width - widget_width) // 2
        y = screen_height - widget_height - 80
        self.root.geometry(f"{widget_width}x{widget_height}+{x}+{y}")
        self.root.configure(bg="#1a1a2e")

        self.frame = tk.Frame(self.root, bg="#16213e", highlightbackground="#4a9eff", highlightthickness=1)
        self.frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.status_label = tk.Label(
            self.frame,
            text="Ready",
            font=("Arial", 11),
            fg="#00ff88",
            bg="#16213e"
        )
        self.status_label.pack(pady=8)

        self.text_label = tk.Label(
            self.frame,
            text=f"Hold {HOTKEY.upper()} to speak...",
            font=("Arial", 10),
            fg="#a0a0a0",
            bg="#16213e"
        )
        self.text_label.pack()

        self.hidden = True
        self.root.withdraw()

        # Handle window close button - quit app entirely
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def hide_widget(self):
        self.hidden = True
        self.root.withdraw()

    def show_widget(self):
        self.hidden = False
        self.root.deiconify()

    def open_settings(self):
        global settings_open, API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE, FILTER_WORDS, config_data
        if settings_open:
            return
        settings_open = True

        win = tk.Toplevel()
        win.title("Voice Type Lite Settings")
        win.geometry("500x620")
        win.configure(bg="#2d2d44")
        win.resizable(False, False)

        tk.Label(win, text="⚙ Voice Type Lite Settings", font=("Arial", 16, "bold"),
                fg="#4a9eff", bg="#2d2d44").pack(pady=15)

        content = tk.Frame(win, bg="#2d2d44")
        content.pack(fill=tk.BOTH, expand=True, padx=25, pady=10)

        # API Key
        tk.Label(content, text="Groq API Key:", fg="white", bg="#2d2d44",
                font=("Arial", 11)).pack(anchor="w")
        api_entry = tk.Entry(content, width=55, bg="#3d3d5c", fg="white",
                            insertbackground="white", font=("Arial", 10), relief="flat")
        api_entry.pack(fill=tk.X, pady=(5, 15), ipady=5)
        api_entry.insert(0, API_KEY)

        # Microphone
        tk.Label(content, text="Microphone:", fg="white", bg="#2d2d44",
                font=("Arial", 11)).pack(anchor="w")
        
        mic_frame = tk.Frame(content, bg="#2d2d44")
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
        mic_menu.config(bg="#3d3d5c", fg="white", font=("Arial", 10), width=48, relief="flat")
        mic_menu.pack(fill=tk.X, ipady=3)

        # Hotkey
        tk.Label(content, text="Push-to-Talk Key:", fg="white", bg="#2d2d44",
                font=("Arial", 11)).pack(anchor="w", pady=(10, 0))
        
        hotkey_frame = tk.Frame(content, bg="#2d2d44")
        hotkey_frame.pack(fill=tk.X, pady=(5, 15))
        
        hotkey_var = tk.StringVar(value=HOTKEY.upper())
        hotkey_entry = tk.Entry(hotkey_frame, width=8, bg="#3d3d5c", fg="#4a9eff",
                               textvariable=hotkey_var, font=("Arial", 14, "bold"),
                               justify="center", relief="flat")
        hotkey_entry.pack(side=tk.LEFT, ipady=5)
        hotkey_entry.config(state="readonly")
        
        tk.Label(hotkey_frame, text="  (click and press a key)", 
                bg="#2d2d44", fg="#888", font=("Arial", 9)).pack(side=tk.LEFT)
        
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

        # Features
        tk.Label(content, text="Features:", fg="white", bg="#2d2d44",
                font=("Arial", 11)).pack(anchor="w", pady=(10, 5))

        accounting_var = tk.BooleanVar(value=ACCOUNTING_MODE)
        tk.Checkbutton(content, text="Accounting Mode (words to numbers)", variable=accounting_var,
                      bg="#2d2d44", fg="white", selectcolor="#3d3d5c",
                      activebackground="#2d2d44", font=("Arial", 10)).pack(anchor="w")

        comma_var = tk.BooleanVar(value=ACCOUNTING_COMMA)
        tk.Checkbutton(content, text="Add commas to large numbers", variable=comma_var,
                      bg="#2d2d44", fg="#aaa", selectcolor="#3d3d5c",
                      activebackground="#2d2d44", font=("Arial", 9)).pack(anchor="w")

        casual_var = tk.BooleanVar(value=CASUAL_MODE)
        tk.Checkbutton(content, text="Casual Mode (lowercase)", variable=casual_var,
                      bg="#2d2d44", fg="white", selectcolor="#3d3d5c",
                      activebackground="#2d2d44", font=("Arial", 10)).pack(anchor="w", pady=(5, 0))

        # Filter
        tk.Label(content, text="Filter Words (comma-separated):", fg="white", bg="#2d2d44",
                font=("Arial", 11)).pack(anchor="w", pady=(15, 0))
        filter_entry = tk.Entry(content, width=55, bg="#3d3d5c", fg="white",
                               insertbackground="white", font=("Arial", 10), relief="flat")
        filter_entry.pack(fill=tk.X, pady=(5, 5), ipady=5)
        filter_entry.insert(0, ", ".join(FILTER_WORDS) if FILTER_WORDS else "")

        # Buttons
        btn_frame = tk.Frame(content, bg="#2d2d44")
        btn_frame.pack(pady=25)

        def save():
            global API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA, CASUAL_MODE, FILTER_WORDS, config_data
            
            API_KEY = api_entry.get().strip()
            
            selected = mic_var.get()
            for i, name in enumerate(mic_names):
                if name == selected and i < len(mics):
                    MIC_INDEX = mics[i][0]
                    print(f"[save] Mic: {MIC_INDEX}")
                    break
            
            new_hotkey = hotkey_var.get().lower()
            if new_hotkey and new_hotkey != "...":
                # Re-register hotkey
                keyboard.unhook_all_hotkeys()
                HOTKEY = new_hotkey
                setup_hotkey()
                print(f"[save] Hotkey: {HOTKEY}")

            ACCOUNTING_MODE = accounting_var.get()
            ACCOUNTING_COMMA = comma_var.get()
            CASUAL_MODE = casual_var.get()
            
            filter_text = filter_entry.get().strip()
            FILTER_WORDS = [w.strip() for w in filter_text.split(",") if w.strip()] if filter_text else []

            config_data["api_key"] = API_KEY
            config_data["mic_index"] = MIC_INDEX
            config_data["hotkey"] = HOTKEY
            config_data["accounting_mode"] = ACCOUNTING_MODE
            config_data["accounting_comma"] = ACCOUNTING_COMMA
            config_data["casual_mode"] = CASUAL_MODE
            config_data["filter_words"] = FILTER_WORDS
            
            try:
                CONFIG_FILE.write_text(json.dumps(config_data))
                print(f"[save] Saved to {CONFIG_FILE}")
                save_btn.config(text="✓ Saved!", bg="#00aa55")
            except Exception as e:
                print(f"[save] ERROR: {e}")
                save_btn.config(text="Error!", bg="#aa0000")
            
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
            os._exit(0)

        save_btn = tk.Button(btn_frame, text="Save", command=save, 
                            bg="#4a9eff", fg="white", font=("Arial", 11, "bold"), 
                            width=12, height=1, relief="raised", borderwidth=2, cursor="hand2")
        save_btn.pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Close", command=close_and_quit, 
                 bg="#555577", fg="white", font=("Arial", 11), 
                 width=12, height=1, relief="raised", borderwidth=2, cursor="hand2").pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Get API Key", 
                 command=lambda: __import__('webbrowser').open("https://console.groq.com/keys"),
                 bg="#8855cc", fg="white", font=("Arial", 11), 
                 width=12, height=1, relief="raised", borderwidth=2, cursor="hand2").pack(side=tk.LEFT, padx=8)

        # When user clicks X on settings window, quit entire app
        win.protocol("WM_DELETE_WINDOW", close_and_quit)

    def quit_app(self):
        global running
        running = False
        keyboard.unhook_all()
        self.root.quit()
        os._exit(0)

    def update_status(self, status, text=""):
        colors = {"ready": "#00ff88", "recording": "#4a9eff", "processing": "#ffc107", 
                  "done": "#00ff88", "error": "#ff5555", "nokey": "#ff5555"}
        status_text = {"ready": "Ready", "recording": "Recording...", "processing": "Transcribing...",
                       "done": "Done", "error": "Error", "nokey": "No API Key"}
        
        self.status_label.configure(text=status_text.get(status, status), fg=colors.get(status, "#ffffff"))
        if text:
            self.text_label.configure(text=text[:40])

    def run(self):
        self.root.mainloop()


widget = None


def transcribe_with_groq(audio_path):
    """Use Groq Whisper API."""
    if not API_KEY:
        return None, "No API key"

    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {API_KEY}"}

        # Read file contents first
        with open(audio_path, "rb") as f:
            audio_data = f.read()

        files = {"file": ("audio.wav", audio_data, "audio/wav")}
        data = {"model": "whisper-large-v3-turbo", "response_format": "json"}

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, files=files, data=data)

        if response.status_code == 200:
            result = response.json()
            return result.get("text"), None
        else:
            error_msg = f"HTTP {response.status_code}"
            try:
                error_detail = response.json()
                if 'error' in error_detail:
                    error_msg += f": {error_detail['error'].get('message', str(error_detail['error']))}"
            except:
                pass
            print(f"[API] Error: {error_msg}")
            return None, error_msg

    except Exception as e:
        print(f"[API] Exception: {e}")
        return None, str(e)


NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90"
}


def convert_numbers(text):
    if not ACCOUNTING_MODE:
        return text
    for word, digit in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        text = re.sub(rf'(?<![a-zA-Z]){word}(?![a-zA-Z])', digit, text, flags=re.IGNORECASE)
    return text


def filter_text(text):
    if not text or not FILTER_WORDS:
        return text.strip() if text else ""
    text_lower = text.lower().strip()
    for fw in FILTER_WORDS:
        if text_lower == fw.lower().strip() or (len(text) < 30 and fw.lower().strip() in text_lower):
            return ""
    return text.strip()


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
        text = text.lower()
        text = re.sub(r'\.\s', ' ', text)
        text = re.sub(r'[!]{2,}', '!', text)
        text = re.sub(r'[?]{2,}', '?', text)
    
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
            widget.update_status("done", text[:30])
            type_text(text)
            time.sleep(1.5)
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