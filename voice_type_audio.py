"""
voice_type_audio.py - Audio recording and Groq Whisper transcription for Voice Type.

All functions accept explicit parameters so this module has no globals and
no imports from voice_type.py (avoids circular imports).
"""

import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
import pyaudio
import wave
import tkinter as tk


# ---------------------------------------------------------------------------
# Groq Whisper transcription
# ---------------------------------------------------------------------------

def transcribe_with_groq(audio_path, api_key, language="auto", custom_vocabulary=None):
    """
    Transcribe an audio file using the Groq Whisper API.
    Returns (text, error) — one of which will be None.
    """
    if not api_key:
        return None, "No API key"

    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(audio_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": "whisper-large-v3-turbo", "response_format": "json"}

            if language and language != "auto":
                data["language"] = language

            if custom_vocabulary:
                vocab_prompt = "Context: " + ", ".join(custom_vocabulary[:50])
                data["prompt"] = vocab_prompt

            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, files=files, data=data)

        if response.status_code == 200:
            return response.json().get("text"), None
        else:
            return None, f"HTTP {response.status_code}"

    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# File transcription (single + batch)
# ---------------------------------------------------------------------------

def transcribe_audio_file(api_key, language, capitalize, autohide, widget,
                          type_text_fn, save_history_fn, update_status_fn,
                          custom_vocabulary=None):
    """
    Open a file-picker dialog then transcribe the selected audio file(s).
    Dispatches to _transcribe_single_file or _transcribe_batch_files.
    """
    if not api_key:
        print("[error] No API key set")
        return

    from tkinter import filedialog

    file_paths = filedialog.askopenfilenames(
        title="Select Audio File(s) - Multiple Files Supported",
        filetypes=[
            ("Audio Files", "*.wav *.mp3 *.m4a *.ogg *.flac *.webm"),
            ("WAV Files", "*.wav"),
            ("MP3 Files", "*.mp3"),
            ("All Files", "*.*"),
        ],
    )

    if not file_paths:
        return

    if len(file_paths) == 1:
        _transcribe_single_file(
            file_paths[0], api_key, language, capitalize, autohide,
            widget, type_text_fn, save_history_fn, update_status_fn,
            custom_vocabulary=custom_vocabulary,
        )
    else:
        _transcribe_batch_files(
            file_paths, api_key, language, capitalize, save_history_fn,
            custom_vocabulary=custom_vocabulary,
        )


def _transcribe_single_file(file_path, api_key, language, capitalize, autohide,
                             widget, type_text_fn, save_history_fn, update_status_fn,
                             custom_vocabulary=None):
    """Transcribe a single audio file and type the result."""
    print(f"[file] Transcribing: {file_path}")
    update_status_fn("processing", "Transcribing file...")
    if widget:
        widget.show_widget()

    def do_transcribe():
        text, error = transcribe_with_groq(
            file_path, api_key, language=language, custom_vocabulary=custom_vocabulary
        )

        if text:
            text = text.strip()
            if capitalize:
                text = text[0].upper() + text[1:] if text else text
                text = re.sub(
                    r'([.!?]\s+)([a-z])',
                    lambda m: m.group(1) + m.group(2).upper(),
                    text,
                )

            word_count = len(text.split())
            char_count = len(text)
            update_status_fn("done", f"{text}\n\n📝 {word_count} words | {char_count} chars")

            import pyperclip
            pyperclip.copy(text)
            print(f"[file] Transcribed: {text[:50]}...")

            save_history_fn(text)
            type_text_fn(text)
        else:
            update_status_fn("error", error or "Failed to transcribe")

        def hide_after():
            time.sleep(3)
            if widget and autohide:
                widget.root.after(0, widget.hide_widget)

        threading.Thread(target=hide_after, daemon=True).start()

    threading.Thread(target=do_transcribe, daemon=True).start()


def _transcribe_batch_files(file_paths, api_key, language, capitalize,
                             save_history_fn, custom_vocabulary=None):
    """Transcribe multiple audio files in batch, writing results to Desktop."""
    print(f"[batch] Transcribing {len(file_paths)} files...")

    batch_win = tk.Toplevel()
    batch_win.title("Batch Transcription")
    batch_win.geometry("500x400")
    batch_win.configure(bg="#1a1a2e")

    tk.Label(
        batch_win,
        text=f"📝 Batch Transcription ({len(file_paths)} files)",
        font=("Segoe UI", 14, "bold"),
        bg="#1a1a2e",
        fg="#4a9eff",
    ).pack(pady=15)

    progress_frame = tk.Frame(batch_win, bg="#1a1a2e")
    progress_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

    scrollbar = tk.Scrollbar(progress_frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    progress_text = tk.Text(
        progress_frame, height=15, bg="#16213e", fg="#ffffff",
        font=("Segoe UI", 9), yscrollcommand=scrollbar.set,
    )
    progress_text.pack(fill=tk.BOTH, expand=True)
    scrollbar.config(command=progress_text.yview)

    results = []

    def append_progress(msg):
        batch_win.after(
            0, lambda: (progress_text.insert(tk.END, msg), progress_text.see(tk.END))
        )

    def process_files():
        for i, file_path in enumerate(file_paths, 1):
            filename = Path(file_path).name
            append_progress(f"[{i}/{len(file_paths)}] Processing: {filename}\n")

            text, error = transcribe_with_groq(
                file_path, api_key, language=language, custom_vocabulary=custom_vocabulary
            )

            if text:
                text = text.strip()
                if capitalize:
                    text = text[0].upper() + text[1:] if text else text
                    text = re.sub(
                        r'([.!?]\s+)([a-z])',
                        lambda m: m.group(1) + m.group(2).upper(),
                        text,
                    )
                word_count = len(text.split())
                results.append({"file": filename, "text": text, "words": word_count, "error": None})
                append_progress(f"  ✅ {word_count} words: {text[:50]}...\n\n")
                save_history_fn(text)
            else:
                results.append({"file": filename, "text": None, "words": 0, "error": error})
                append_progress(f"  ❌ Error: {error}\n\n")

            time.sleep(0.5)

        if results:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            desktop = Path.home() / "Desktop"
            if not desktop.exists():
                desktop = Path.home()
            output_file = desktop / f"batch_transcription_{timestamp}.txt"

            with open(output_file, "w", encoding="utf-8") as f:
                f.write("Batch Transcription Results\n")
                f.write(f"Processed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total files: {len(results)}\n")
                f.write("=" * 60 + "\n\n")
                for r in results:
                    f.write(f"File: {r['file']}\n")
                    f.write(f"Words: {r['words']}\n")
                    if r["text"]:
                        f.write(f"Text:\n{r['text']}\n\n")
                    else:
                        f.write(f"Error: {r['error']}\n\n")
                    f.write("-" * 60 + "\n\n")

            append_progress(f"\n✅ Batch complete! Saved to: {output_file}\n")
            append_progress(
                f"Total: {sum(r['words'] for r in results)} words from {len(results)} files\n"
            )

    threading.Thread(target=process_files, daemon=True).start()

    tk.Button(
        batch_win, text="Close", font=("Segoe UI", 11),
        bg="#4a9eff", fg="#ffffff", command=batch_win.destroy,
    ).pack(pady=10)
