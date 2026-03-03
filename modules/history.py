"""
voice_type_history.py - History, statistics, and export for Voice Type.

Functions accept explicit parameters so this module has no globals and
no imports from voice_type.py (avoids circular imports).
"""

import csv
import json
import time
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def save_to_history(text, history, history_file, max_history, history_enabled, auto_save):
    """
    Prepend text to history list, persist to disk, and trigger weekly backup.
    Returns the (possibly trimmed) updated history list.
    """
    if not history_enabled or not text:
        return history

    entry = {
        "text": text,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "words": len(text.split()),
    }
    history = [entry] + history

    if max_history and len(history) > max_history:
        history = history[:max_history]

    try:
        Path(history_file).write_text(json.dumps(history, indent=2))
    except Exception as e:
        print(f"[history] Error saving: {e}")

    if auto_save:
        _auto_backup_history(history)

    return history


def _auto_backup_history(history):
    """Write a weekly backup of history to ~/VoiceType Backups/."""
    backup_dir = Path.home() / "VoiceType Backups"
    backup_dir.mkdir(exist_ok=True)

    week_num = datetime.now().isocalendar()[1]
    year = datetime.now().year
    backup_file = backup_dir / f"history_week_{year}_{week_num:02d}.json"

    if not backup_file.exists():
        try:
            backup_file.write_text(json.dumps(history, indent=2))
            print(f"[backup] Weekly backup saved: {backup_file.name}")
        except Exception as e:
            print(f"[backup] Error: {e}")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_history(history):
    """Open a format-selection dialog then write the export file."""
    if not history:
        print("[export] No history to export")
        return

    import tkinter as tk

    popup = tk.Tk()
    popup.title("Export History - Choose Format")
    popup.configure(bg="#1a1a2e")
    popup.resizable(False, False)
    popup.attributes("-topmost", True)

    popup.update_idletasks()
    w, h = 300, 200
    x = (popup.winfo_screenwidth() // 2) - (w // 2)
    y = (popup.winfo_screenheight() // 2) - (h // 2)
    popup.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(popup, text="📁 Export Format", font=("Segoe UI", 14, "bold"),
             bg="#1a1a2e", fg="#4a9eff").pack(pady=20)

    selected_format = tk.StringVar(value="txt")
    for fmt, label in [("txt", "📄 Text File (.txt)"), ("json", "📊 JSON (.json)"),
                        ("md", "📝 Markdown (.md)"), ("csv", "📈 CSV Spreadsheet (.csv)")]:
        tk.Radiobutton(popup, text=label, variable=selected_format, value=fmt,
                       bg="#1a1a2e", fg="#ffffff", selectcolor="#16213e",
                       activebackground="#1a1a2e", activeforeground="#ffffff",
                       font=("Segoe UI", 10)).pack(anchor="w", padx=30, pady=2)

    def do_export():
        popup.destroy()
        _export_to_format(selected_format.get(), history)

    tk.Button(popup, text="Export", font=("Segoe UI", 11, "bold"),
              bg="#4a9eff", fg="#ffffff", command=do_export).pack(pady=20)

    popup.mainloop()


def _export_to_format(format_type, history):
    """Write history to the Desktop in the requested format."""
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if format_type == "txt":
            export_file = desktop / f"voice_type_history_{timestamp}.txt"
            with open(export_file, "w", encoding="utf-8") as f:
                f.write("VoiceType Transcription History\n")
                f.write(f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Total entries: {len(history)}\n")
                f.write("=" * 50 + "\n\n")
                for i, entry in enumerate(history, 1):
                    f.write(f"[{entry.get('timestamp', 'Unknown')}] ({entry.get('words', 0)} words)\n")
                    f.write(f"{entry.get('text', '')}\n\n")

        elif format_type == "json":
            export_file = desktop / f"voice_type_history_{timestamp}.json"
            export_data = {
                "exported": datetime.now().isoformat(),
                "total_entries": len(history),
                "history": history,
            }
            with open(export_file, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

        elif format_type == "md":
            export_file = desktop / f"voice_type_history_{timestamp}.md"
            with open(export_file, "w", encoding="utf-8") as f:
                f.write("# VoiceType Transcription History\n\n")
                f.write(f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Total entries:** {len(history)}\n\n---\n\n")
                for i, entry in enumerate(history, 1):
                    f.write(f"## Entry {i}\n\n")
                    f.write(f"**Time:** {entry.get('timestamp', 'Unknown')}\n\n")
                    f.write(f"**Words:** {entry.get('words', 0)}\n\n")
                    f.write(f"**Text:**\n\n{entry.get('text', '')}\n\n---\n\n")

        elif format_type == "csv":
            export_file = desktop / f"voice_type_history_{timestamp}.csv"
            with open(export_file, "w", encoding="utf-8", newline='') as f:
                writer = csv.writer(f)
                writer.writerow(["Entry", "Timestamp", "Words", "Text"])
                for i, entry in enumerate(history, 1):
                    writer.writerow([i, entry.get('timestamp', ''), entry.get('words', 0), entry.get('text', '')])

        print(f"[export] Exported {len(history)} entries to {export_file}")

    except Exception as e:
        print(f"[export] Error: {e}")


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def update_stats(text, stats, stats_file):
    """
    Increment word/transcription counters in stats dict and persist to disk.
    Returns the updated stats dict.
    """
    stats["total_words"] += len(text.split())
    stats["total_transcriptions"] += 1
    stats["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if stats["first_used"] is None:
        stats["first_used"] = stats["last_used"]

    try:
        Path(stats_file).write_text(json.dumps(stats, indent=2))
    except Exception:
        pass

    return stats
