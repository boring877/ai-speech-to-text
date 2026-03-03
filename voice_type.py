"""
Voice Type - Hold Shift to speak, release to type.
Uses Groq Whisper API for fast, accurate speech-to-text.
"""

__version__ = "2.4.0"
__author__ = "Anton AI Agent"

import json
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

if sys.stdout:
    sys.stdout.reconfigure(line_buffering=True)
if sys.stderr:
    sys.stderr.reconfigure(line_buffering=True)

print("Loading Voice Type...")

import keyboard
import pyaudio
import pyperclip
import wave

from modules.core import (
    CONFIG_FILE, SAMPLE_RATE, DEFAULT_FILTER_WORDS,
    convert_numbers_to_digits,
    filter_text as _filter_text_core,
    normalize_numbers_from_api as _normalize_numbers_core,
    format_number_with_commas as _format_commas_core,
    apply_casual_mode as _apply_casual_core,
)
from modules.data import DEFAULT_MACROS, QUICK_SNIPPETS
from modules.features import (
    convert_emojis, auto_add_kaomoji, apply_macros, process_voice_commands,
)
from modules.history import save_to_history, update_stats, export_history
from modules.audio import transcribe_with_groq, transcribe_audio_file
from modules.ui import (
    FloatingWidget, create_tray_icon,
    show_shortcuts_overlay, show_snippets_popup, show_language_switcher,
    shortcuts_visible, snippets_visible, language_switcher_visible,
)

print("Ready!")

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
MACROS_FILE = Path.home() / ".voice-type-macros.json"
STATS_FILE  = Path.home() / ".voice-type-stats.json"
HISTORY_FILE = Path.home() / ".voice-type-history.json"

# ---------------------------------------------------------------------------
# Default stats
# ---------------------------------------------------------------------------
DEFAULT_STATS = {
    "total_words": 0,
    "total_sessions": 0,
    "total_transcriptions": 0,
    "total_minutes": 0.0,
    "first_used": None,
    "last_used": None,
}

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
config_data = {
    "api_key": "",
    "mic_index": None,
    "hotkey": "shift",
    "accounting_mode": False,
    "history_enabled": True,
    "quicken_mode": False,
    "language": "auto",
    "auto_stop": False,
    "silence_threshold": 2.0,
    "always_on_top": True,
    "autohide": True,
    "compact_mode": False,
    "accent_color": "#6366f1",
    "save_audio": False,
    "auto_copy": True,
    "show_timer": True,
    "minimize_startup": False,
    "widget_position": None,
    "noise_threshold": 0.01,
    "recording_delay": 0.0,
    "auto_punctuation": True,
    "custom_vocabulary": [],
    "word_replacements": {},
    "max_history": 100,
    "auto_save_transcriptions": True,
    "punctuation": {
        "periods": True, "commas": True, "question_marks": True,
        "exclamation_marks": True, "colons": True, "semicolons": True, "quotes": True,
    },
    "filter_words": list(DEFAULT_FILTER_WORDS),
    "kaomoji_mode": False,
    "casual_mode": False,
    "accounting_comma": False,
    "theme": "dark",
    "capitalize_sentences": True,
    "smart_quotes": False,
    "double_space_period": False,
}
if CONFIG_FILE.exists():
    try:
        saved = json.loads(CONFIG_FILE.read_text())
        config_data.update(saved)
    except Exception as e:
        print(f"[config] Error loading: {e}")

# Backward compat: old config location
old_config = Path.home() / "voice-type-config.txt"
if not config_data.get("api_key") and old_config.exists():
    config_data["api_key"] = old_config.read_text().strip()

# ---------------------------------------------------------------------------
# Module-level globals (extracted from config for fast reads inside hot paths)
# ---------------------------------------------------------------------------
API_KEY             = config_data.get("api_key", "")
MIC_INDEX           = config_data.get("mic_index")
HOTKEY              = config_data.get("hotkey", "shift")
ACCOUNTING_MODE     = config_data.get("accounting_mode", False)
ACCOUNTING_COMMA    = config_data.get("accounting_comma", False)
CAPITALIZE_SENTENCES = config_data.get("capitalize_sentences", True)
SMART_QUOTES        = config_data.get("smart_quotes", False)
CASUAL_MODE         = config_data.get("casual_mode", False)
THEME               = config_data.get("theme", "dark")
HISTORY_ENABLED     = config_data.get("history_enabled", True)
QUICKEN_MODE        = config_data.get("quicken_mode", False)
LANGUAGE            = config_data.get("language", "auto")
AUTO_STOP           = config_data.get("auto_stop", False)
SILENCE_THRESHOLD   = config_data.get("silence_threshold", 2.0)
ALWAYS_ON_TOP       = config_data.get("always_on_top", True)
AUTOHIDE_ENABLED    = config_data.get("autohide", True)
COMPACT_MODE        = config_data.get("compact_mode", False)
ACCENT_COLOR        = config_data.get("accent_color", "#6366f1")
SAVE_AUDIO          = config_data.get("save_audio", False)
AUTO_COPY           = config_data.get("auto_copy", True)
SHOW_TIMER          = config_data.get("show_timer", True)
MINIMIZE_STARTUP    = config_data.get("minimize_startup", False)
WIDGET_POSITION     = config_data.get("widget_position", None)
CUSTOM_VOCABULARY   = config_data.get("custom_vocabulary", [])
WORD_REPLACEMENTS   = config_data.get("word_replacements", {})
FILTER_WORDS        = config_data.get("filter_words", list(DEFAULT_FILTER_WORDS))
KAOMOJI_MODE        = config_data.get("kaomoji_mode", False)
MAX_HISTORY         = config_data.get("max_history", 100)
AUTO_SAVE_TRANSCRIPTIONS = config_data.get("auto_save_transcriptions", True)
PUNCTUATION         = config_data.get("punctuation", {})

# ---------------------------------------------------------------------------
# Macros
# ---------------------------------------------------------------------------
MACROS = DEFAULT_MACROS.copy()
if MACROS_FILE.exists():
    try:
        user_macros = json.loads(MACROS_FILE.read_text())
        MACROS.update(user_macros)
        print(f"[startup] Loaded {len(user_macros)} custom macros")
    except Exception as e:
        print(f"[startup] Error loading macros: {e}")

# ---------------------------------------------------------------------------
# Stats + History
# ---------------------------------------------------------------------------
STATS = DEFAULT_STATS.copy()
if STATS_FILE.exists():
    try:
        STATS.update(json.loads(STATS_FILE.read_text()))
    except Exception as e:
        print(f"[startup] Error loading stats: {e}")

HISTORY = []
if HISTORY_FILE.exists() and HISTORY_ENABLED:
    try:
        HISTORY = json.loads(HISTORY_FILE.read_text())
        print(f"[startup] Loaded {len(HISTORY)} history items")
    except Exception as e:
        print(f"[startup] Error loading history: {e}")

print(f"[startup] Config file: {CONFIG_FILE}")

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------

class State:
    recording = False
    running   = True

state = State()
widget    = None
tray_icon = None
last_transcription = ""


# ---------------------------------------------------------------------------
# Auto-start (Windows)
# ---------------------------------------------------------------------------

def set_autostart(enabled):
    """Enable or disable auto-start on Windows boot."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "VoiceType"
        if enabled:
            exe_path = (
                sys.executable if getattr(sys, "frozen", False)
                else f'"{sys.executable}" "{Path(__file__).resolve()}"'
            )
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
            winreg.CloseKey(key)
            print(f"[autostart] Enabled: {exe_path}")
        else:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            try:
                winreg.DeleteValue(key, app_name)
                print("[autostart] Disabled")
            except FileNotFoundError:
                pass
            winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"[autostart] Error: {e}")
        return False


# ---------------------------------------------------------------------------
# Status wrapper (posts to widget from any thread)
# ---------------------------------------------------------------------------

def update_status(status_key, text=""):
    if widget:
        widget.root.after(0, lambda: widget.update_status(status_key, text))


# ---------------------------------------------------------------------------
# Thin wrappers around voice_type_core functions (consume module globals)
# ---------------------------------------------------------------------------

def filter_text(text):
    return _filter_text_core(text, FILTER_WORDS)

def normalize_numbers_from_api(text):
    return _normalize_numbers_core(text, ACCOUNTING_COMMA)

def format_number_with_commas(text):
    return _format_commas_core(text)

def apply_casual_mode(text):
    if not CASUAL_MODE:
        return text
    return _apply_casual_core(text)


# ---------------------------------------------------------------------------
# Callbacks for settings save / quit / etc.
# ---------------------------------------------------------------------------

def on_settings_saved():
    """Re-read all globals from config_data after settings dialog saves."""
    global API_KEY, MIC_INDEX, HOTKEY, ACCOUNTING_MODE, ACCOUNTING_COMMA
    global CAPITALIZE_SENTENCES, SMART_QUOTES, CASUAL_MODE, THEME, HISTORY_ENABLED
    global QUICKEN_MODE, LANGUAGE, AUTO_STOP, SILENCE_THRESHOLD, ALWAYS_ON_TOP
    global AUTOHIDE_ENABLED, COMPACT_MODE, ACCENT_COLOR, SAVE_AUDIO, AUTO_COPY
    global SHOW_TIMER, MINIMIZE_STARTUP, WIDGET_POSITION, CUSTOM_VOCABULARY
    global WORD_REPLACEMENTS, FILTER_WORDS, KAOMOJI_MODE, MAX_HISTORY
    global AUTO_SAVE_TRANSCRIPTIONS, PUNCTUATION

    API_KEY             = config_data.get("api_key", "")
    MIC_INDEX           = config_data.get("mic_index")
    HOTKEY              = config_data.get("hotkey", "shift")
    ACCOUNTING_MODE     = config_data.get("accounting_mode", False)
    ACCOUNTING_COMMA    = config_data.get("accounting_comma", False)
    CAPITALIZE_SENTENCES = config_data.get("capitalize_sentences", True)
    SMART_QUOTES        = config_data.get("smart_quotes", False)
    CASUAL_MODE         = config_data.get("casual_mode", False)
    THEME               = config_data.get("theme", "dark")
    HISTORY_ENABLED     = config_data.get("history_enabled", True)
    QUICKEN_MODE        = config_data.get("quicken_mode", False)
    LANGUAGE            = config_data.get("language", "auto")
    AUTO_STOP           = config_data.get("auto_stop", False)
    SILENCE_THRESHOLD   = config_data.get("silence_threshold", 2.0)
    ALWAYS_ON_TOP       = config_data.get("always_on_top", True)
    AUTOHIDE_ENABLED    = config_data.get("autohide", True)
    COMPACT_MODE        = config_data.get("compact_mode", False)
    ACCENT_COLOR        = config_data.get("accent_color", "#6366f1")
    SAVE_AUDIO          = config_data.get("save_audio", False)
    AUTO_COPY           = config_data.get("auto_copy", True)
    SHOW_TIMER          = config_data.get("show_timer", True)
    MINIMIZE_STARTUP    = config_data.get("minimize_startup", False)
    WIDGET_POSITION     = config_data.get("widget_position")
    CUSTOM_VOCABULARY   = config_data.get("custom_vocabulary", [])
    WORD_REPLACEMENTS   = config_data.get("word_replacements", {})
    FILTER_WORDS        = config_data.get("filter_words", list(DEFAULT_FILTER_WORDS))
    KAOMOJI_MODE        = config_data.get("kaomoji_mode", False)
    MAX_HISTORY         = config_data.get("max_history", 100)
    AUTO_SAVE_TRANSCRIPTIONS = config_data.get("auto_save_transcriptions", True)
    PUNCTUATION         = config_data.get("punctuation", {})

    if sys.platform == "win32" and "autostart" in config_data:
        set_autostart(config_data.get("autostart", False))


def on_stats_reset():
    global STATS
    STATS = DEFAULT_STATS.copy()
    try:
        STATS_FILE.write_text(json.dumps(STATS, indent=2))
    except Exception:
        pass


def on_quit():
    state.running = False
    keyboard.unhook_all()
    if tray_icon:
        tray_icon.stop()
    widget.root.quit()
    sys.exit(0)


def on_language_change(code):
    global LANGUAGE
    LANGUAGE = code
    config_data["language"] = code
    CONFIG_FILE.write_text(json.dumps(config_data))


def _save_history(text):
    """Wrapper so other modules can save history with one argument."""
    global HISTORY
    HISTORY = save_to_history(
        text, HISTORY, HISTORY_FILE, MAX_HISTORY,
        HISTORY_ENABLED, AUTO_SAVE_TRANSCRIPTIONS,
    )


# ---------------------------------------------------------------------------
# type_text — orchestrator (reads many globals, calls feature/history modules)
# ---------------------------------------------------------------------------

def type_text(text):
    """Normalise, filter, expand macros, handle commands, then type the text."""
    global last_transcription, STATS, HISTORY

    text = normalize_numbers_from_api(text)

    if ACCOUNTING_MODE:
        text = convert_numbers_to_digits(text)
        if ACCOUNTING_COMMA:
            text = format_number_with_commas(text)

    text = filter_text(text)
    if not text:
        print("[filtered] Text was filtered out, nothing to type")
        return

    text = apply_macros(text, MACROS)

    text, last_transcription = process_voice_commands(text, last_transcription, type_text)
    if text is None:
        print("[command] Action command executed")
        return

    text = convert_emojis(text, KAOMOJI_MODE)
    text = auto_add_kaomoji(text, KAOMOJI_MODE)
    text = apply_casual_mode(text)

    STATS = update_stats(text, STATS, STATS_FILE)
    _save_history(text)

    print(f"[typing] {text}")

    if QUICKEN_MODE:
        for char in text:
            keyboard.write(char)
            time.sleep(0.01)
        keyboard.write(" ")
    else:
        old_clip = ""
        if not AUTO_COPY:
            try:
                old_clip = pyperclip.paste()
            except Exception:
                pass
        pyperclip.copy(text)
        time.sleep(0.05)
        keyboard.press_and_release("ctrl+v")
        if not AUTO_COPY:
            time.sleep(0.05)
            try:
                pyperclip.copy(old_clip)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# record_and_transcribe — top-level recording loop (stays here; touches widget
# and many globals, so it doesn't belong in a sub-module)
# ---------------------------------------------------------------------------

def record_and_transcribe():
    """Record audio while hotkey is held, then transcribe with Groq Whisper."""
    global last_transcription, HISTORY, STATS

    if widget and widget.hidden:
        widget.root.after(0, widget.show_widget)
    update_status("recording", "Speak now...")
    print("Recording...")

    try:
        mic_idx = MIC_INDEX if MIC_INDEX is not None else 0
        p = pyaudio.PyAudio()
        chunk    = 1024
        fmt      = pyaudio.paInt16
        channels = 1
        rate     = SAMPLE_RATE

        stream = p.open(
            format=fmt, channels=channels, rate=rate,
            input=True, input_device_index=mic_idx,
            frames_per_buffer=chunk,
        )

        frames = []
        silence_start = None

        while keyboard.is_pressed(HOTKEY):
            data = stream.read(chunk, exception_on_overflow=False)
            frames.append(data)

            samples  = struct.unpack(f"<{len(data)//2}h", data)
            max_samp = max(abs(s) for s in samples) if samples else 0
            level    = min(max_samp / 32768.0, 1.0)

            if widget:
                widget.root.after(0, lambda l=level: widget.update_level(l))

            if AUTO_STOP:
                if level > 0.02:
                    silence_start = None
                else:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start >= SILENCE_THRESHOLD:
                        print(f"[auto-stop] {SILENCE_THRESHOLD}s silence detected")
                        break

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

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        wf = wave.open(temp_path, "wb")
        wf.setnchannels(channels)
        wf.setsampwidth(p.get_sample_size(fmt))
        wf.setframerate(rate)
        wf.writeframes(b"".join(frames))
        wf.close()

        text, error = transcribe_with_groq(
            temp_path, API_KEY, language=LANGUAGE,
            custom_vocabulary=CUSTOM_VOCABULARY,
        )

        if SAVE_AUDIO and text:
            audio_dir = Path.home() / "VoiceType Recordings"
            audio_dir.mkdir(exist_ok=True)
            audio_file = audio_dir / f"recording_{time.strftime('%Y%m%d_%H%M%S')}.wav"
            shutil.copy(temp_path, audio_file)
            print(f"[audio] Saved to {audio_file}")

        Path(temp_path).unlink(missing_ok=True)

        if text:
            text = text.strip()

            if CAPITALIZE_SENTENCES:
                text = text[0].upper() + text[1:] if text else text
                text = re.sub(
                    r"([.!?]\s+)([a-z])",
                    lambda m: m.group(1) + m.group(2).upper(),
                    text,
                )

            if SMART_QUOTES:
                result = []
                in_quote = False
                for char in text:
                    if char == '"':
                        result.append('\u201d' if in_quote else '\u201c')
                        in_quote = not in_quote
                    else:
                        result.append(char)
                text = "".join(result)

            if WORD_REPLACEMENTS:
                for old, new in WORD_REPLACEMENTS.items():
                    text = text.replace(old, new)

            print(f"[whisper] {text}")
            last_transcription = text

            if AUTO_COPY:
                pyperclip.copy(text)

            word_count = len(text.split())
            char_count = len(text)
            update_status("done", f"{text}\n\n📝 {word_count} words | {char_count} chars")
            type_text(text)

            def hide_after_done():
                time.sleep(2)
                if widget and AUTOHIDE_ENABLED:
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


# ---------------------------------------------------------------------------
# Hotkey polling loop
# ---------------------------------------------------------------------------

def hotkey_loop():
    """Poll hotkey and function keys at 50 Hz."""
    was_pressed = False
    while state.running:
        is_pressed = keyboard.is_pressed(HOTKEY)
        if is_pressed and not was_pressed and not state.recording:
            was_pressed = True
            state.recording = True
            threading.Thread(target=record_and_transcribe, daemon=True).start()
        elif not is_pressed and was_pressed:
            was_pressed = False

        if keyboard.is_pressed("f1") and not shortcuts_visible():
            keyboard.release("f1")
            time.sleep(0.1)
            threading.Thread(
                target=show_shortcuts_overlay, args=(HOTKEY,), daemon=True
            ).start()

        if keyboard.is_pressed("f2") and not snippets_visible():
            keyboard.release("f2")
            time.sleep(0.1)
            threading.Thread(
                target=show_snippets_popup, args=(QUICK_SNIPPETS, type_text), daemon=True
            ).start()

        if keyboard.is_pressed("f3") and not language_switcher_visible():
            keyboard.release("f3")
            time.sleep(0.1)
            threading.Thread(
                target=show_language_switcher,
                args=(config_data, on_language_change),
                daemon=True,
            ).start()

        time.sleep(0.02)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global widget, tray_icon, STATS

    print("=" * 50)
    print(f"Voice Type v{__version__} - Groq Whisper (Hold {HOTKEY.upper()})")
    print("=" * 50)

    STATS["total_sessions"] += 1
    try:
        STATS_FILE.write_text(json.dumps(STATS, indent=2))
    except Exception:
        pass

    if not API_KEY:
        print("\n  No API key found!")
        print("Get free key: https://console.groq.com/keys")
    else:
        print(f"API key loaded ({len(API_KEY)} chars)")

    if MACROS:
        print(f"Macros loaded: {len(MACROS)}")

    callbacks = {
        "get_last_transcription": lambda: last_transcription,
        "get_history":            lambda: HISTORY,
        "get_stats":              lambda: STATS,
        "on_stats_reset":         on_stats_reset,
        "on_settings_saved":      on_settings_saved,
        "transcribe_file":        lambda: transcribe_audio_file(
            API_KEY, LANGUAGE, CAPITALIZE_SENTENCES, AUTOHIDE_ENABLED,
            widget, type_text, _save_history, update_status,
            custom_vocabulary=CUSTOM_VOCABULARY,
        ),
        "export_history":         lambda: export_history(HISTORY),
        "on_quit":                on_quit,
    }

    widget = FloatingWidget(config_data, state, __version__, callbacks)

    if MINIMIZE_STARTUP:
        widget.hide_widget()
        print("Started minimized to tray")

    tray_icon = create_tray_icon(widget, __version__, HOTKEY, callbacks)
    widget.tray_icon = tray_icon
    threading.Thread(target=tray_icon.run, daemon=True).start()

    threading.Thread(target=hotkey_loop, daemon=True).start()

    print(f"\nReady! Hold {HOTKEY.upper()} to record.")

    widget.root.after(500, widget.open_settings)

    try:
        widget.run()
    except KeyboardInterrupt:
        on_quit()


if __name__ == "__main__":
    main()
