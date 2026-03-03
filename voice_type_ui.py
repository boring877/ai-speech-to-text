"""
voice_type_ui.py - FloatingWidget, tray icon, and popup dialogs for Voice Type.

FloatingWidget accepts a mutable `config` dict (which IS config_data in voice_type.py),
a `state` object reference, a `version` string, and a `callbacks` dict so this module
has no imports from voice_type.py (avoids circular imports).

Required callbacks keys:
    get_last_transcription()  -> str
    get_history()             -> list
    get_stats()               -> dict
    on_stats_reset()          -> None   (resets stats in caller)
    on_settings_saved()       -> None   (propagates config changes to caller's globals)
    transcribe_file()         -> None   (opens file-transcription picker)
    on_quit()                 -> None   (stops state, tray, process)
"""

import json
import sys
import threading
import time
from pathlib import Path

import keyboard
import pyaudio
import pyperclip
import pystray
import tkinter as tk
from tkinter import font as tkfont, ttk, messagebox
from PIL import Image, ImageDraw

from voice_type_core import CONFIG_FILE, DEFAULT_FILTER_WORDS

# ---------------------------------------------------------------------------
# Module-level popup-visibility flags
# ---------------------------------------------------------------------------
_shortcuts_visible = False
_snippets_visible = False
_language_switcher_visible = False


# ---------------------------------------------------------------------------
# FloatingWidget
# ---------------------------------------------------------------------------

class FloatingWidget:
    """Floating status window with settings, history browser, and context menu."""

    def __init__(self, config, state, version, callbacks):
        """
        config    – mutable config_data dict (shared with voice_type.py)
        state     – State() instance (has .running and .recording)
        version   – version string for display
        callbacks – dict of callable hooks (see module docstring)
        """
        self.config = config
        self.state = state
        self.version = version
        self.callbacks = callbacks
        self.settings_open = False
        self.tray_icon = None  # set externally after create_tray_icon()

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", config.get("always_on_top", True))
        self.root.attributes("-toolwindow", False)

        self.apply_theme(config.get("theme", "dark"))

    def apply_theme(self, theme_name):
        """Apply color theme (dark or light) with custom accent color."""
        accent = self.config.get("accent_color") or "#6366f1"

        if theme_name == "light":
            self.bg_dark = "#f5f5f5"
            self.bg_medium = "#ffffff"
            self.bg_light = "#e8e8e8"
            self.accent_primary = accent
            self.accent_secondary = "#6b5b95"
            self.accent_success = "#28a745"
            self.accent_warning = "#ffc107"
            self.text_primary = "#1a1a1a"
            self.text_secondary = "#666666"
            self.border_color = accent
        else:
            self.bg_dark = "#1a1a2e"
            self.bg_medium = "#16213e"
            self.bg_light = "#0f3460"
            self.accent_primary = accent
            self.accent_secondary = "#533483"
            self.accent_success = "#00ff88"
            self.accent_warning = "#ffc107"
            self.text_primary = "#ffffff"
            self.text_secondary = "#a0a0a0"
            self.border_color = accent

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        if self.config.get("compact_mode"):
            w, h = 200, 60
        else:
            w, h = 320, 130

        pos = self.config.get("widget_position")
        if pos and len(pos) == 2:
            x, y = pos
            if x < 0 or x > screen_w - w:
                x = (screen_w - w) // 2
            if y < 0 or y > screen_h - h:
                y = screen_h - h - 100
        else:
            x = (screen_w - w) // 2
            y = screen_h - h - 100

        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.current_x = x
        self.current_y = y
        self.root.configure(bg=self.bg_dark)

        # Rebuild widgets only when apply_theme is called during init or full rebuild
        if hasattr(self, "main_frame"):
            self.main_frame.destroy()

        self.main_frame = tk.Frame(
            self.root, bg=self.bg_dark,
            highlightbackground=self.border_color, highlightthickness=2,
        )
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.content_frame = tk.Frame(self.main_frame, bg=self.bg_medium)
        self.content_frame.pack(fill=tk.BOTH, expand=True, padx=3, pady=3)

        # Status row
        self.status_frame = tk.Frame(self.content_frame, bg=self.bg_medium)
        self.status_frame.pack(fill=tk.X, padx=15, pady=(12, 5))

        self.status_font = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        self.status_label = tk.Label(
            self.status_frame, text="● Ready",
            font=self.status_font, fg=self.accent_success, bg=self.bg_medium,
        )
        self.status_label.pack(side=tk.LEFT)

        self.rec_indicator = tk.Label(
            self.status_frame, text="",
            font=("Segoe UI", 10), fg=self.accent_primary, bg=self.bg_medium,
        )
        self.rec_indicator.pack(side=tk.RIGHT)

        self.timer_label = tk.Label(
            self.status_frame, text="",
            font=("Segoe UI", 10), fg=self.text_secondary, bg=self.bg_medium,
        )
        self.timer_label.pack(side=tk.RIGHT, padx=(0, 10))

        tk.Frame(self.content_frame, height=1, bg=self.border_color).pack(
            fill=tk.X, padx=15, pady=8
        )

        hotkey = self.config.get("hotkey", "shift").upper()
        self.text_font = tkfont.Font(family="Segoe UI", size=11)
        self.text_label = tk.Label(
            self.content_frame,
            text=f"Hold {hotkey} to speak...",
            font=self.text_font, fg=self.text_secondary, bg=self.bg_medium, wraplength=280,
        )
        self.text_label.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 5))

        self.hint_label = tk.Label(
            self.content_frame,
            text=f"Press {hotkey} to record | Right-click tray for settings | v{self.version}",
            font=("Segoe UI", 8), fg=self.text_secondary, bg=self.bg_medium,
        )
        self.hint_label.pack(fill=tk.X, padx=15, pady=(0, 5))

        # Audio level bar
        level_frame = tk.Frame(self.content_frame, bg=self.bg_medium)
        level_frame.pack(fill=tk.X, padx=15, pady=(0, 5))
        self.level_canvas = tk.Canvas(
            level_frame, width=280, height=8,
            bg=self.bg_light, highlightthickness=0,
        )
        self.level_canvas.pack(fill=tk.X)
        self.level_bar = self.level_canvas.create_rectangle(
            0, 0, 0, 8, fill=self.accent_success, outline=""
        )
        self.current_level = 0

        self.colors = {
            "ready":      (self.accent_success, "● Ready"),
            "recording":  (self.accent_primary, "● Recording"),
            "processing": (self.accent_warning, "◐ Transcribing"),
            "done":       (self.accent_success, "✓ Done"),
            "error":      (self.accent_primary, "✕ Error"),
            "nokey":      (self.accent_primary, "✕ No API Key"),
        }

        # Drag
        self.drag_start_x = 0
        self.drag_start_y = 0
        for w in (self.content_frame, self.status_label, self.text_label):
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.drag)
            w.bind("<ButtonRelease-1>", self.end_drag)

        # Context menu
        self.context_menu = tk.Menu(
            self.root, tearoff=0,
            bg=self.bg_dark, fg=self.text_primary,
            activebackground=self.accent_primary, activeforeground="white",
        )
        self.context_menu.add_command(label="📋 Copy Last", command=self.copy_last)
        self.context_menu.add_command(label="📜 History", command=self.open_history)
        self.context_menu.add_command(
            label="📁 Transcribe File...",
            command=lambda: threading.Thread(
                target=self.callbacks["transcribe_file"], daemon=True
            ).start(),
        )
        self.context_menu.add_separator()
        self.context_menu.add_command(label="⚙️ Settings", command=self.open_settings)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="📌 Always on Top", command=self.toggle_topmost)
        self.context_menu.add_command(label="👁️ Show/Hide", command=self.toggle_visibility)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="❌ Minimize", command=self.hide_widget)

        for w in (self.content_frame, self.status_label, self.text_label):
            w.bind("<Button-3>", self.show_context_menu)

        self.hidden = True
        self.root.withdraw()

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def show_context_menu(self, event):
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def copy_last(self):
        text = self.callbacks["get_last_transcription"]()
        if text:
            pyperclip.copy(text)

    def toggle_topmost(self):
        new_val = not self.config.get("always_on_top", True)
        self.config["always_on_top"] = new_val
        self.root.attributes("-topmost", new_val)
        CONFIG_FILE.write_text(json.dumps(self.config))

    def toggle_visibility(self):
        if self.hidden:
            self.show_widget()
        else:
            self.hide_widget()

    # ------------------------------------------------------------------
    # Drag
    # ------------------------------------------------------------------

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def drag(self, event):
        x = self.root.winfo_x() + event.x - self.drag_start_x
        y = self.root.winfo_y() + event.y - self.drag_start_y
        self.root.geometry(f"+{x}+{y}")
        self.current_x = x
        self.current_y = y

    def end_drag(self, _event):
        self.save_position()

    def save_position(self):
        self.config["widget_position"] = [self.current_x, self.current_y]
        CONFIG_FILE.write_text(json.dumps(self.config))

    # ------------------------------------------------------------------
    # Visibility
    # ------------------------------------------------------------------

    def hide_widget(self):
        self.hidden = True
        self.root.withdraw()

    def show_widget(self):
        self.hidden = False
        self.root.deiconify()

    # ------------------------------------------------------------------
    # Level indicator
    # ------------------------------------------------------------------

    def update_level(self, level):
        if not hasattr(self, "level_canvas"):
            return
        self.current_level = self.current_level * 0.7 + level * 0.3
        bar_width = int(280 * min(self.current_level, 1.0))
        self.level_canvas.coords(self.level_bar, 0, 0, bar_width, 8)
        if self.current_level < 0.3:
            color = self.accent_success
        elif self.current_level < 0.7:
            color = self.accent_warning
        else:
            color = "#ff4444"
        self.level_canvas.itemconfig(self.level_bar, fill=color)

    # ------------------------------------------------------------------
    # Status / timer
    # ------------------------------------------------------------------

    def update_status(self, status_key, text=""):
        color, status_text = self.colors.get(status_key, self.colors["ready"])
        display = f"{status_text} {text}" if text else status_text
        self.status_label.configure(text=display, fg=color)
        if text and status_key == "done":
            self.text_label.configure(text=text, fg="#f8f8f2")
        elif status_key == "recording":
            self.text_label.configure(text="Speak now...", fg="#f8f8f2")
            if self.config.get("show_timer", True):
                self.start_timer()
        elif status_key == "processing":
            self.text_label.configure(text="Transcribing...", fg="#f8f8f2")
            self.stop_timer()

    def start_timer(self):
        self.recording_start = time.time()
        self.timer_running = True
        self.update_timer()

    def stop_timer(self):
        self.timer_running = False

    def update_timer(self):
        if not self.timer_running:
            return
        elapsed = time.time() - self.recording_start
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        timer_text = f"⏱ {mins}:{secs:02d}" if mins > 0 else f"⏱ {secs}s"
        if hasattr(self, "timer_label"):
            self.timer_label.configure(text=timer_text)
        self.root.after(100, self.update_timer)

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def open_settings(self):
        if self.settings_open:
            return
        self.settings_open = True

        cfg = self.config
        win = tk.Toplevel()
        win.title(f"VoiceType v{self.version} Settings")
        win.geometry("550x600")
        win.configure(bg=self.bg_dark)
        win.resizable(False, False)

        label_style = {
            "bg": self.bg_dark, "fg": self.text_secondary, "font": ("Segoe UI", 10)
        }
        input_style = {
            "bg": self.bg_light, "fg": self.text_primary,
            "insertbackground": self.text_primary, "relief": "flat", "font": ("Segoe UI", 10)
        }

        # Header
        header = tk.Frame(win, bg=self.bg_medium, height=45)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(
            header, text="⚙ VoiceType Settings",
            font=("Segoe UI", 13, "bold"), fg=self.border_color, bg=self.bg_medium,
        ).pack(pady=10)
        tk.Frame(win, height=2, bg=self.border_color).pack(fill=tk.X)

        # Tab bar
        tab_bar = tk.Frame(win, bg=self.bg_dark)
        tab_bar.pack(fill=tk.X, padx=10, pady=5)
        tabs = {}
        tab_frames = {}
        current_tab = tk.StringVar(value="General")

        def switch_tab(tab_name):
            for name, frame in tab_frames.items():
                frame.pack_forget()
            for name, btn in tabs.items():
                btn.configure(
                    bg=self.bg_light if name == tab_name else self.bg_medium,
                    fg=self.border_color if name == tab_name else self.text_secondary,
                )
            tab_frames[tab_name].pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
            current_tab.set(tab_name)

        for i, tab_name in enumerate(["General", "Recording", "Appearance", "Advanced"]):
            btn = tk.Button(
                tab_bar, text=tab_name, font=("Segoe UI", 10, "bold"),
                bg=self.border_color if i == 0 else self.bg_medium,
                fg="white" if i == 0 else self.text_secondary,
                relief="flat", cursor="hand2", width=12,
                command=lambda t=tab_name: switch_tab(t),
            )
            btn.pack(side=tk.LEFT, padx=2)
            tabs[tab_name] = btn

        content_area = tk.Frame(win, bg=self.bg_dark)
        content_area.pack(fill=tk.BOTH, expand=True)

        for tab_name in ["General", "Recording", "Appearance", "Advanced"]:
            tab_frames[tab_name] = tk.Frame(content_area, bg=self.bg_dark)

        # ── GENERAL TAB ──────────────────────────────────────────────
        gen = tab_frames["General"]

        tk.Label(gen, text="🔐 API Key", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))
        tk.Label(gen, text="Groq API Key:", **label_style).pack(anchor="w")
        api_entry = tk.Entry(gen, width=60, **input_style)
        api_entry.pack(fill=tk.X, pady=(5, 15))
        api_entry.insert(0, cfg.get("api_key", ""))

        tk.Label(gen, text="🎤 Microphone", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        tk.Label(gen, text="Input device:", **label_style).pack(anchor="w")

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Settings.TCombobox",
            fieldbackground=self.bg_light, background=self.bg_light,
            foreground=self.text_primary,
        )
        mic_combo = ttk.Combobox(gen, width=57, style="Settings.TCombobox",
                                  font=("Segoe UI", 10))
        mic_combo.pack(fill=tk.X, pady=(5, 15))

        p = pyaudio.PyAudio()
        mics = []
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev["maxInputChannels"] > 0:
                mics.append((i, dev["name"]))
        p.terminate()
        mic_combo["values"] = [f"{i}: {n}" for i, n in mics]
        mic_index = cfg.get("mic_index")
        if mic_index is not None:
            for idx, (i, _n) in enumerate(mics):
                if i == mic_index:
                    mic_combo.current(idx)
                    break
        elif mics:
            mic_combo.current(0)

        tk.Label(gen, text="⌨ Push-to-Talk Key", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        hotkey_frame = tk.Frame(gen, bg=self.bg_dark)
        hotkey_frame.pack(fill=tk.X, pady=(5, 15))
        hotkey_var = tk.StringVar(value=cfg.get("hotkey", "shift").upper())
        hotkey_entry = tk.Entry(
            hotkey_frame, width=10, bg=self.bg_light, fg=self.border_color,
            textvariable=hotkey_var, font=("Segoe UI", 12, "bold"),
            justify="center", relief="flat",
        )
        hotkey_entry.pack(side=tk.LEFT)
        hotkey_entry.config(state="readonly")

        def on_hotkey_focus(_e):
            hotkey_entry.config(state="normal")
            hotkey_var.set("...")
            hotkey_entry.config(state="readonly")

        def on_hotkey_keypress(event):
            special_keys = {
                16: "shift", 17: "ctrl", 18: "alt", 32: "space",
                112: "f1", 113: "f2", 114: "f3", 115: "f4", 116: "f5",
                117: "f6", 118: "f7", 119: "f8", 120: "f9", 121: "f10",
                122: "f11", 123: "f12",
            }
            key_name = special_keys.get(
                event.keycode,
                event.keysym.lower() if event.keysym and len(event.keysym) == 1
                else event.keysym.lower(),
            )
            if key_name:
                hotkey_entry.config(state="normal")
                hotkey_var.set(key_name.upper())
                hotkey_entry.config(state="readonly")
            return "break"

        hotkey_entry.bind("<FocusIn>", on_hotkey_focus)
        hotkey_entry.bind("<KeyPress>", on_hotkey_keypress)
        tk.Label(hotkey_frame, text="  (click and press a key)",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(side=tk.LEFT)

        tk.Label(gen, text="🌍 Language", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(0, 5))
        lang_frame = tk.Frame(gen, bg=self.bg_dark)
        lang_frame.pack(fill=tk.X, pady=(5, 15))
        language_var = tk.StringVar(value=cfg.get("language", "auto"))
        lang_options = [
            "auto", "en", "es", "fr", "de", "it", "pt", "ru",
            "ja", "ko", "zh", "ar", "hi", "nl", "pl", "tr", "el", "sq", "he", "fa",
        ]
        ttk.Combobox(lang_frame, textvariable=language_var, values=lang_options,
                     state="readonly", width=15).pack(side=tk.LEFT)
        tk.Label(lang_frame, text="  (auto = detect automatically)",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(side=tk.LEFT)

        # ── RECORDING TAB ─────────────────────────────────────────────
        rec = tab_frames["Recording"]

        tk.Label(rec, text="✨ Transcription Features", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))

        accounting_var = tk.BooleanVar(value=cfg.get("accounting_mode", False))
        tk.Checkbutton(rec, text="🔢 Accounting Mode (convert 'one' → '1')",
                       variable=accounting_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        comma_var = tk.BooleanVar(value=cfg.get("accounting_comma", False))
        tk.Checkbutton(rec, text="   └─ Add commas to large numbers",
                       variable=comma_var, bg=self.bg_dark, fg=self.text_secondary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 9), cursor="hand2").pack(anchor="w", pady=2)

        casual_var = tk.BooleanVar(value=cfg.get("casual_mode", False))
        tk.Checkbutton(rec, text="💬 Casual Mode (lowercase, informal)",
                       variable=casual_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        kaomoji_var = tk.BooleanVar(value=cfg.get("kaomoji_mode", False))
        tk.Checkbutton(
            rec,
            text="(◕‿◕) Kaomoji Mode — replace emojis with Japanese emoticons",
            variable=kaomoji_var, bg=self.bg_dark, fg=self.text_primary,
            selectcolor=self.bg_light, activebackground=self.bg_dark,
            font=("Segoe UI", 10), cursor="hand2",
        ).pack(anchor="w", pady=2)
        tk.Label(rec, text='   Say "kaomoji happy", "kaomoji sad", "kaomoji shrug" etc.',
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(
            anchor="w", pady=(0, 4)
        )

        quicken_var = tk.BooleanVar(value=cfg.get("quicken_mode", False))
        tk.Checkbutton(rec, text="🧾 Quicken Mode (character-by-character)",
                       variable=quicken_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=10)

        tk.Label(rec, text="🎤 Recording Options", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))

        autostop_var = tk.BooleanVar(value=cfg.get("auto_stop", False))
        tk.Checkbutton(rec, text="🔇 Auto-stop after silence",
                       variable=autostop_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        auto_copy_var = tk.BooleanVar(value=cfg.get("auto_copy", True))
        tk.Checkbutton(rec, text="📋 Auto-copy to clipboard",
                       variable=auto_copy_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        show_timer_var = tk.BooleanVar(value=cfg.get("show_timer", True))
        tk.Checkbutton(rec, text="⏱ Show recording timer",
                       variable=show_timer_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        tk.Label(rec, text="🚫 Filter Words", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))
        tk.Label(rec, text="Phrases to block (comma-separated):",
                 **label_style).pack(anchor="w")
        filter_entry = tk.Entry(rec, width=60, **input_style)
        filter_entry.pack(fill=tk.X, pady=(5, 5))
        filter_words = cfg.get("filter_words", DEFAULT_FILTER_WORDS)
        filter_entry.insert(0, ", ".join(filter_words) if filter_words else "")
        tk.Label(rec, text="Example: thank you, thanks",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(anchor="w")

        # ── APPEARANCE TAB ────────────────────────────────────────────
        app = tab_frames["Appearance"]

        tk.Label(app, text="🎨 Theme", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))
        theme_frame = tk.Frame(app, bg=self.bg_dark)
        theme_frame.pack(fill=tk.X, pady=(5, 10))
        theme_var = tk.StringVar(value=cfg.get("theme", "dark"))
        for val, label in [("dark", "Dark"), ("light", "Light")]:
            tk.Radiobutton(
                theme_frame, text=label, variable=theme_var, value=val,
                bg=self.bg_dark, fg=self.text_primary, selectcolor=self.bg_light,
                activebackground=self.bg_dark, font=("Segoe UI", 10),
            ).pack(side=tk.LEFT, padx=10)

        tk.Label(app, text="🎨 Accent Color", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))
        accent_frame = tk.Frame(app, bg=self.bg_dark)
        accent_frame.pack(fill=tk.X, pady=(5, 10))
        accent_var = tk.StringVar(value=cfg.get("accent_color", "#6366f1"))
        for color, name in [
            ("#6366f1", "Purple"), ("#10b981", "Green"), ("#f59e0b", "Orange"),
            ("#ef4444", "Red"), ("#3b82f6", "Blue"), ("#ec4899", "Pink"),
        ]:
            tk.Radiobutton(
                accent_frame, text=name, variable=accent_var, value=color,
                bg=self.bg_dark, fg=self.text_primary, selectcolor=color,
                activebackground=self.bg_dark, font=("Segoe UI", 9),
            ).pack(side=tk.LEFT, padx=5)

        tk.Label(app, text="📱 Widget Options", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))

        ontop_var = tk.BooleanVar(value=cfg.get("always_on_top", True))
        tk.Checkbutton(app, text="📌 Always on top",
                       variable=ontop_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        autohide_var = tk.BooleanVar(value=cfg.get("autohide", True))
        tk.Checkbutton(app, text="👁 Auto-hide after transcription",
                       variable=autohide_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        compact_var = tk.BooleanVar(value=cfg.get("compact_mode", False))
        tk.Checkbutton(app, text="📐 Compact mode (smaller widget)",
                       variable=compact_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        # Statistics display
        tk.Label(app, text="📊 Statistics", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))
        stats_frame = tk.Frame(app, bg=self.bg_light, padx=10, pady=10)
        stats_frame.pack(fill=tk.X, pady=5)

        stats = self.callbacks["get_stats"]()
        stats_words_label = tk.Label(
            stats_frame, text=f"📝 Words typed: {stats.get('total_words', 0):,}",
            bg=self.bg_light, fg=self.text_primary, font=("Segoe UI", 10),
        )
        stats_words_label.pack(anchor="w")
        stats_trans_label = tk.Label(
            stats_frame, text=f"🎤 Transcriptions: {stats.get('total_transcriptions', 0):,}",
            bg=self.bg_light, fg=self.text_primary, font=("Segoe UI", 10),
        )
        stats_trans_label.pack(anchor="w")

        stats_reset_label = tk.Label(
            stats_frame, text="", bg=self.bg_light, fg=self.accent_success,
            font=("Segoe UI", 9),
        )
        stats_reset_label.pack(anchor="w")

        def do_reset_stats():
            self.callbacks["on_stats_reset"]()
            stats_words_label.config(text="📝 Words typed: 0")
            stats_trans_label.config(text="🎤 Transcriptions: 0")
            stats_reset_label.config(text="✓ Reset!")
            win.after(1500, lambda: stats_reset_label.config(text=""))

        tk.Button(stats_frame, text="Reset Stats", command=do_reset_stats,
                  bg=self.bg_medium, fg=self.text_primary, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2").pack(anchor="w", pady=(5, 0))

        # ── ADVANCED TAB ──────────────────────────────────────────────
        adv = tab_frames["Advanced"]

        tk.Label(adv, text="🚀 Startup", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(10, 5))

        autostart_var = None
        if sys.platform == "win32":
            autostart_var = tk.BooleanVar(value=cfg.get("autostart", False))
            tk.Checkbutton(
                adv, text="Start with Windows", variable=autostart_var,
                bg=self.bg_dark, fg=self.text_primary, selectcolor=self.bg_light,
                activebackground=self.bg_dark, font=("Segoe UI", 10), cursor="hand2",
            ).pack(anchor="w", pady=2)

        minimize_var = tk.BooleanVar(value=cfg.get("minimize_startup", False))
        tk.Checkbutton(adv, text="Start minimized to tray",
                       variable=minimize_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        tk.Label(adv, text="🎵 Audio", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))

        save_audio_var = tk.BooleanVar(value=cfg.get("save_audio", False))
        tk.Checkbutton(adv, text="💾 Save audio recordings",
                       variable=save_audio_var, bg=self.bg_dark, fg=self.text_primary,
                       selectcolor=self.bg_light, activebackground=self.bg_dark,
                       font=("Segoe UI", 10), cursor="hand2").pack(anchor="w", pady=2)

        # Macros
        tk.Label(adv, text="🔧 Voice Macros", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))
        macros_file = Path.home() / ".voice-type-macros.json"
        macros_count = len(json.loads(macros_file.read_text())) if macros_file.exists() else 0
        tk.Label(adv, text=f"Loaded: {macros_count} macros",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(adv, text="Edit file: ~/.voice-type-macros.json",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(anchor="w")

        def open_macros():
            import subprocess
            if not macros_file.exists():
                macros_file.write_text(json.dumps({
                    "thank you": "Thank you for your help!",
                    "best regards": "Best regards, [Your Name]",
                }, indent=2))
            if sys.platform == "win32":
                subprocess.run(["notepad", str(macros_file)])
            else:
                subprocess.run(["nano", str(macros_file)])

        tk.Button(adv, text="📝 Edit Macros File", command=open_macros,
                  bg=self.bg_light, fg=self.text_primary, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2").pack(anchor="w", pady=5)

        # Word replacements
        tk.Label(adv, text="🔄 Word Replacements", font=("Segoe UI", 11, "bold"),
                 fg=self.border_color, bg=self.bg_dark).pack(anchor="w", pady=(15, 5))
        rep_file = Path.home() / ".voice-type-replacements.json"
        tk.Label(adv, text="Edit file: ~/.voice-type-replacements.json",
                 bg=self.bg_dark, fg=self.text_secondary, font=("Segoe UI", 9)).pack(anchor="w")

        def open_replacements():
            import subprocess
            if not rep_file.exists():
                rep_file.write_text(json.dumps(
                    {"gonna": "going to", "wanna": "want to"}, indent=2
                ))
            if sys.platform == "win32":
                subprocess.run(["notepad", str(rep_file)])
            else:
                subprocess.run(["nano", str(rep_file)])

        tk.Button(adv, text="📝 Edit Replacements File", command=open_replacements,
                  bg=self.bg_light, fg=self.text_primary, font=("Segoe UI", 9),
                  relief="flat", cursor="hand2").pack(anchor="w", pady=5)

        # Show first tab
        switch_tab("General")

        # ── Button bar ────────────────────────────────────────────────
        btn_bar = tk.Frame(win, bg=self.bg_dark)
        btn_bar.pack(fill=tk.X, padx=10, pady=10)

        def save():
            cfg["api_key"] = api_entry.get().strip()
            selected_mic = mic_combo.get()
            if selected_mic:
                cfg["mic_index"] = int(selected_mic.split(":")[0])
            cfg["hotkey"] = hotkey_var.get().lower()
            cfg["accounting_mode"] = accounting_var.get()
            cfg["accounting_comma"] = comma_var.get()
            cfg["casual_mode"] = casual_var.get()
            cfg["kaomoji_mode"] = kaomoji_var.get()
            cfg["filter_words"] = [
                w.strip() for w in filter_entry.get().split(",") if w.strip()
            ]
            cfg["theme"] = theme_var.get()
            cfg["quicken_mode"] = quicken_var.get()
            cfg["language"] = language_var.get()
            cfg["auto_stop"] = autostop_var.get()
            cfg["always_on_top"] = ontop_var.get()
            cfg["autohide"] = autohide_var.get()
            cfg["compact_mode"] = compact_var.get()
            cfg["accent_color"] = accent_var.get()
            cfg["save_audio"] = save_audio_var.get()
            cfg["auto_copy"] = auto_copy_var.get()
            cfg["show_timer"] = show_timer_var.get()
            cfg["minimize_startup"] = minimize_var.get()
            if autostart_var is not None:
                cfg["autostart"] = autostart_var.get()

            CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

            # Apply theme + topmost immediately
            self.apply_theme(cfg["theme"])
            self.root.configure(bg=self.bg_dark)
            self.root.attributes("-topmost", cfg["always_on_top"])

            # Propagate to caller's globals
            self.callbacks["on_settings_saved"]()

            messagebox.showinfo("Saved", "Settings saved successfully!")
            close_settings()

        def reset_defaults():
            if not messagebox.askyesno("Reset", "Reset all settings to defaults?"):
                return
            defaults = {
                "api_key": "", "mic_index": None, "hotkey": "shift",
                "accounting_mode": False, "accounting_comma": False,
                "casual_mode": False, "kaomoji_mode": False,
                "filter_words": list(DEFAULT_FILTER_WORDS),
                "theme": "dark", "quicken_mode": False, "language": "auto",
                "auto_stop": False, "always_on_top": True, "autohide": True,
                "compact_mode": False, "accent_color": "#6366f1",
                "save_audio": False, "auto_copy": True, "show_timer": True,
                "minimize_startup": False,
            }
            cfg.update(defaults)
            CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
            self.callbacks["on_settings_saved"]()
            messagebox.showinfo("Reset", "Settings reset. Reopen settings to see changes.")
            close_settings()

        def close_settings():
            self.settings_open = False
            win.destroy()

        tk.Button(btn_bar, text="💾 Save", command=save,
                  bg=self.border_color, fg="white", font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_bar, text="🔄 Reset", command=reset_defaults,
                  bg="#ef4444", fg="white", font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_bar, text="❌ Close", command=close_settings,
                  bg=self.bg_light, fg=self.text_primary, font=("Segoe UI", 10, "bold"),
                  relief="flat", cursor="hand2", width=12).pack(side=tk.LEFT, padx=5)

        win.protocol("WM_DELETE_WINDOW", close_settings)

    # ------------------------------------------------------------------
    # History browser
    # ------------------------------------------------------------------

    def open_history(self):
        history = self.callbacks["get_history"]()
        if not history:
            return

        win = tk.Toplevel(self.root)
        win.title(f"VoiceType v{self.version} - History")
        win.geometry("500x400")
        win.configure(bg=self.bg_dark)

        search_frame = tk.Frame(win, bg=self.bg_dark)
        search_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Label(search_frame, text="🔍", bg=self.bg_dark, fg=self.text_primary,
                 font=("Segoe UI", 12)).pack(side=tk.LEFT)
        search_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=search_var,
                 bg=self.bg_light, fg=self.text_primary,
                 insertbackground=self.text_primary,
                 font=("Segoe UI", 11), width=40).pack(side=tk.LEFT, padx=5)

        results_frame = tk.Frame(win, bg=self.bg_dark)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(results_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox = tk.Listbox(
            results_frame, bg=self.bg_light, fg=self.text_primary,
            font=("Segoe UI", 10), selectmode=tk.SINGLE,
            yscrollcommand=scrollbar.set,
        )
        listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        filtered_history = list(history)

        def copy_selected():
            sel = listbox.curselection()
            if sel:
                pyperclip.copy(filtered_history[sel[0]].get("text", ""))

        btn_frame = tk.Frame(win, bg=self.bg_dark)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(btn_frame, text="📋 Copy Selected", command=copy_selected,
                  bg=self.border_color, fg=self.text_primary,
                  font=("Segoe UI", 10)).pack(side=tk.LEFT)

        def update_results(*_args):
            nonlocal filtered_history
            query = search_var.get().lower()
            listbox.delete(0, tk.END)
            filtered_history = []
            for entry in history:
                text = entry.get("text", "").lower()
                if not query or query in text:
                    filtered_history.append(entry)
                    ts = entry.get("timestamp", "")
                    preview = entry.get("text", "")[:50]
                    listbox.insert(tk.END, f"[{ts}] {preview}...")

        search_var.trace("w", update_results)
        update_results()

        win.transient(self.root)
        win.grab_set()

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def quit_app(self):
        self.callbacks["on_quit"]()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------

def create_tray_icon(widget, version, hotkey, callbacks):
    """
    Create and return a pystray.Icon.

    callbacks must have:
        get_last_transcription()  -> str
        export_history()          -> None
        transcribe_file()         -> None
    """
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(img)
    dc.ellipse([20, 8, 44, 36], fill="#50fa7b", outline="#50fa7b")
    dc.rectangle([28, 36, 36, 48], fill="#50fa7b")
    dc.arc([12, 32, 52, 56], 0, 180, fill="#50fa7b", width=3)
    dc.line([32, 52, 32, 60], fill="#50fa7b", width=3)
    dc.line([22, 60, 42, 60], fill="#50fa7b", width=3)

    def on_settings(icon, item):
        widget.root.after(0, widget.open_settings)

    def on_copy_last(icon, item):
        text = callbacks["get_last_transcription"]()
        if text:
            pyperclip.copy(text)
            print(f"[clipboard] Copied: {text[:50]}...")

    def on_show(icon, item):
        widget.root.after(0, widget.show_widget)

    def on_history(icon, item):
        widget.root.after(0, widget.open_history)

    def on_export(icon, item):
        callbacks["export_history"]()

    def on_transcribe_file(icon, item):
        callbacks["transcribe_file"]()

    def on_quit(icon, item):
        widget.root.after(0, widget.quit_app)

    menu = pystray.Menu(
        pystray.MenuItem("Settings", on_settings),
        pystray.MenuItem("History", on_history),
        pystray.MenuItem("Export History", on_export),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("📁 Transcribe Audio File...", on_transcribe_file),
        pystray.MenuItem("Copy Last", on_copy_last, default=False),
        pystray.MenuItem("Show Widget", on_show),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    return pystray.Icon(
        "voice_type", img,
        f"VoiceType v{version} (Hold {hotkey.upper()})",
        menu,
    )


# ---------------------------------------------------------------------------
# Popup dialogs (standalone, called from hotkey_loop)
# ---------------------------------------------------------------------------

def show_shortcuts_overlay(hotkey):
    """Show keyboard shortcuts overlay (F1)."""
    global _shortcuts_visible
    if _shortcuts_visible:
        return
    _shortcuts_visible = True

    overlay = tk.Tk()
    overlay.title("VoiceType - Keyboard Shortcuts")
    overlay.configure(bg="#1a1a2e")
    overlay.resizable(False, False)
    overlay.attributes("-topmost", True)
    overlay.update_idletasks()
    w, h = 400, 450
    x = (overlay.winfo_screenwidth() // 2) - (w // 2)
    y = (overlay.winfo_screenheight() // 2) - (h // 2)
    overlay.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(overlay, text="⌨️ Keyboard Shortcuts", font=("Segoe UI", 16, "bold"),
             bg="#1a1a2e", fg="#4a9eff").pack(pady=20)

    shortcuts = [
        ("Recording", f"Hold {hotkey.upper()}", "Push-to-talk"),
        ("", "", ""),
        ("Voice Commands", "", ""),
        ("Delete last word", '"delete last word"', 'or "undo that"'),
        ("Delete sentence", '"delete last sentence"', ""),
        ("New paragraph", '"new paragraph"', 'or "new line"'),
        ("Punctuation", '"period", "comma"', '"question mark"'),
        ("Select all", '"select all"', "Selects all text"),
        ("Copy/Paste", '"copy that" / "paste"', "Clipboard"),
        ("Repeat last", '"repeat last"', "Type last again"),
        ("", "", ""),
        ("In-App", "", ""),
        ("Show shortcuts", "F1", "This overlay"),
        ("Quick snippets", "F2", "Common phrases"),
        ("Language switcher", "F3", "Switch languages"),
        ("Settings", "Right-click tray", "Open settings"),
        ("Context menu", "Right-click widget", "Quick actions"),
        ("Quit", "Right-click tray → Quit", ""),
        ("", "", ""),
        ("Press ESC or click to close", "", ""),
    ]

    frame = tk.Frame(overlay, bg="#1a1a2e")
    frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    for action, shortcut, note in shortcuts:
        row = tk.Frame(frame, bg="#1a1a2e")
        row.pack(fill=tk.X, pady=2)
        if action and not action.startswith("Press"):
            tk.Label(row, text=action, font=("Segoe UI", 10, "bold"),
                     bg="#1a1a2e", fg="#ffffff", width=20, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=shortcut, font=("Segoe UI", 10),
                     bg="#1a1a2e", fg="#00ff88", width=25, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=note, font=("Segoe UI", 9),
                     bg="#1a1a2e", fg="#a0a0a0", anchor="w").pack(side=tk.LEFT)
        elif action.startswith("Press"):
            tk.Label(row, text=action, font=("Segoe UI", 10, "italic"),
                     bg="#1a1a2e", fg="#a0a0a0").pack(side=tk.LEFT)
        else:
            tk.Label(row, text=shortcut, font=("Segoe UI", 11, "bold"),
                     bg="#1a1a2e", fg="#533483").pack(side=tk.LEFT)

    def close(_e=None):
        global _shortcuts_visible
        _shortcuts_visible = False
        overlay.destroy()

    overlay.bind("<Escape>", close)
    overlay.bind("<Button-1>", close)
    overlay.protocol("WM_DELETE_WINDOW", close)
    overlay.mainloop()


def show_snippets_popup(snippets, type_text_fn):
    """Show quick-snippets popup (F2)."""
    global _snippets_visible
    if _snippets_visible:
        return
    _snippets_visible = True

    popup = tk.Tk()
    popup.title("VoiceType - Quick Snippets")
    popup.configure(bg="#1a1a2e")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)
    popup.update_idletasks()
    w, h = 450, 400
    x = (popup.winfo_screenwidth() // 2) - (w // 2)
    y = (popup.winfo_screenheight() // 2) - (h // 2)
    popup.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(popup, text="📝 Quick Snippets (F2)", font=("Segoe UI", 16, "bold"),
             bg="#1a1a2e", fg="#4a9eff").pack(pady=15)
    tk.Label(popup, text="Click a snippet to type it instantly", font=("Segoe UI", 10),
             bg="#1a1a2e", fg="#a0a0a0").pack(pady=(0, 10))

    frame = tk.Frame(popup, bg="#1a1a2e")
    frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    def close_popup():
        global _snippets_visible
        _snippets_visible = False
        popup.destroy()

    def insert_snippet(_name, text):
        type_text_fn(text)
        close_popup()

    for name, text in snippets.items():
        preview = f"{text[:40]}..." if len(text) > 40 else text
        tk.Button(
            frame, text=f"📌 {name}: {preview}",
            font=("Segoe UI", 10), bg="#16213e", fg="#ffffff",
            activebackground="#4a9eff", activeforeground="#ffffff",
            cursor="hand2", anchor="w", padx=10,
            command=lambda n=name, t=text: insert_snippet(n, t),
        ).pack(fill=tk.X, pady=2)

    popup.protocol("WM_DELETE_WINDOW", close_popup)
    popup.bind("<Escape>", lambda _e: close_popup())
    popup.bind("<FocusOut>", lambda _e: close_popup())
    popup.mainloop()


def show_language_switcher(config, on_language_change):
    """Show language-switcher popup (F3)."""
    global _language_switcher_visible
    if _language_switcher_visible:
        return
    _language_switcher_visible = True

    popup = tk.Tk()
    popup.title("VoiceType - Language Switcher (F3)")
    popup.configure(bg="#1a1a2e")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)
    popup.update_idletasks()
    w, h = 350, 500
    x = (popup.winfo_screenwidth() // 2) - (w // 2)
    y = (popup.winfo_screenheight() // 2) - (h // 2)
    popup.geometry(f"{w}x{h}+{x}+{y}")

    current_lang = config.get("language", "auto")
    display_lang = current_lang if current_lang != "auto" else "auto-detect"

    tk.Label(popup, text="🌍 Language Switcher", font=("Segoe UI", 16, "bold"),
             bg="#1a1a2e", fg="#4a9eff").pack(pady=15)
    tk.Label(popup, text="Click a language to switch instantly", font=("Segoe UI", 10),
             bg="#1a1a2e", fg="#a0a0a0").pack(pady=(0, 10))
    tk.Label(popup, text=f"Current: {display_lang}", font=("Segoe UI", 10, "bold"),
             bg="#1a1a2e", fg="#00ff88").pack(pady=(0, 15))

    frame = tk.Frame(popup, bg="#1a1a2e")
    frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    languages = [
        ("auto", "🌍 Auto-Detect"), ("en", "🇬🇧 English"), ("es", "🇪🇸 Spanish"),
        ("fr", "🇫🇷 French"), ("de", "🇩🇪 German"), ("it", "🇮🇹 Italian"),
        ("pt", "🇵🇹 Portuguese"), ("ru", "🇷🇺 Russian"), ("ja", "🇯🇵 Japanese"),
        ("ko", "🇰🇷 Korean"), ("zh", "🇨🇳 Chinese"), ("ar", "🇸🇦 Arabic"),
        ("el", "🇬🇷 Greek"), ("sq", "🇦🇱 Albanian"), ("hi", "🇮🇳 Hindi"),
        ("nl", "🇳🇱 Dutch"), ("pl", "🇵🇱 Polish"), ("tr", "🇹🇷 Turkish"),
        ("he", "🇮🇱 Hebrew"), ("vi", "🇻🇳 Vietnamese"),
    ]

    def close_popup():
        global _language_switcher_visible
        _language_switcher_visible = False
        popup.destroy()

    def select_language(code, name):
        on_language_change(code)
        print(f"[language] Switched to: {name} ({code})")
        close_popup()

    for code, name in languages:
        is_current = code == current_lang or (code == "auto" and current_lang == "auto")
        tk.Button(
            frame, text=name,
            font=("Segoe UI", 10),
            bg="#4a9eff" if is_current else "#16213e", fg="#ffffff",
            activebackground="#4a9eff", activeforeground="#ffffff",
            cursor="hand2", anchor="w", padx=10,
            command=lambda c=code, n=name: select_language(c, n),
        ).pack(fill=tk.X, pady=2)

    popup.protocol("WM_DELETE_WINDOW", close_popup)
    popup.bind("<Escape>", lambda _e: close_popup())
    popup.bind("<FocusOut>", lambda _e: close_popup())
    popup.mainloop()


# ---------------------------------------------------------------------------
# Visibility helpers (for hotkey_loop to query)
# ---------------------------------------------------------------------------

def shortcuts_visible():
    return _shortcuts_visible

def snippets_visible():
    return _snippets_visible

def language_switcher_visible():
    return _language_switcher_visible
