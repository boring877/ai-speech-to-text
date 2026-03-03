"""
voice_type_features.py - Text feature functions for Voice Type.

All functions take explicit parameters (no module globals), matching the
style of voice_type_core.py. This makes them testable and import-safe.
"""

import re
import time

import keyboard

from voice_type_data import (
    EMOJI_MAP,
    KAOMOJI_MAP,
    EMOJI_TO_KAOMOJI,
    KAOMOJI_AUTO_TRIGGERS,
    VOICE_COMMANDS,
)


def convert_emojis(text, kaomoji_mode):
    """Convert emoji/kaomoji voice phrases to their character equivalents."""
    result = text

    # Explicit kaomoji commands always apply (e.g. "kaomoji happy")
    for phrase, kaomoji in sorted(KAOMOJI_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        result = pattern.sub(kaomoji, result)

    if kaomoji_mode:
        combined = {**EMOJI_MAP, **EMOJI_TO_KAOMOJI}
        for phrase, char in sorted(combined.items(), key=lambda x: len(x[0]), reverse=True):
            replacement = EMOJI_TO_KAOMOJI.get(phrase, char)
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            result = pattern.sub(replacement, result)
    else:
        for phrase, emoji in sorted(EMOJI_MAP.items(), key=lambda x: len(x[0]), reverse=True):
            pattern = re.compile(re.escape(phrase), re.IGNORECASE)
            result = pattern.sub(emoji, result)

    return re.sub(r'\s+', ' ', result).strip()


def auto_add_kaomoji(text, kaomoji_mode):
    """Detect emotion keywords and append a matching kaomoji (Kaomoji Mode only)."""
    if not kaomoji_mode:
        return text
    # Don't double-add if text already contains a kaomoji
    for kaomoji in KAOMOJI_MAP.values():
        if kaomoji in text:
            return text
    for pattern, kaomoji in KAOMOJI_AUTO_TRIGGERS:
        if re.search(pattern, text, re.IGNORECASE):
            return text.rstrip() + " " + kaomoji
    return text


def apply_macros(text, macros):
    """Expand voice macro shortcuts, replacing {{DATE}}/{{TIME}}/{{DATETIME}} placeholders."""
    if not macros:
        return text

    result = text
    today = time.strftime("%Y-%m-%d")
    now = time.strftime("%H:%M:%S")
    dt = time.strftime("%Y-%m-%d %H:%M:%S")

    for phrase, expansion in sorted(macros.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        expansion = expansion.replace("{{DATE}}", today)
        expansion = expansion.replace("{{TIME}}", now)
        expansion = expansion.replace("{{DATETIME}}", dt)
        result = pattern.sub(expansion, result)

    return re.sub(r'\s+', ' ', result).strip()


def process_voice_commands(text, last_transcription, type_text_fn):
    """
    Process voice commands embedded in text.

    Returns (processed_text, new_last_transcription).
    processed_text is None if the command was an action (delete/copy/etc.)
    that was already executed.
    """
    text_lower = text.lower().strip()

    if text_lower in VOICE_COMMANDS:
        command_value = VOICE_COMMANDS[text_lower]

        if command_value == "__DELETE_WORD__":
            print("[command] Delete last word")
            keyboard.press_and_release("ctrl+backspace")
            return None, last_transcription
        elif command_value == "__DELETE_SENTENCE__":
            print("[command] Delete last sentence")
            keyboard.press_and_release("ctrl+shift+left")
            keyboard.press_and_release("backspace")
            return None, last_transcription
        elif command_value == "__DELETE_ALL__":
            print("[command] Delete all")
            keyboard.press_and_release("ctrl+a")
            keyboard.press_and_release("backspace")
            return None, last_transcription
        elif command_value == "__SELECT_ALL__":
            print("[command] Select all")
            keyboard.press_and_release("ctrl+a")
            return None, last_transcription
        elif command_value == "__COPY__":
            print("[command] Copy")
            keyboard.press_and_release("ctrl+c")
            return None, last_transcription
        elif command_value == "__PASTE__":
            print("[command] Paste")
            keyboard.press_and_release("ctrl+v")
            return None, last_transcription
        elif command_value == "__CUT__":
            print("[command] Cut")
            keyboard.press_and_release("ctrl+x")
            return None, last_transcription
        elif command_value == "__UNDO__":
            print("[command] Undo")
            keyboard.press_and_release("ctrl+z")
            return None, last_transcription
        elif command_value == "__REDO__":
            print("[command] Redo")
            keyboard.press_and_release("ctrl+y")
            return None, last_transcription
        elif command_value == "__REPEAT_LAST__":
            print("[command] Repeat last transcription")
            if last_transcription:
                type_text_fn(last_transcription)
            return None, last_transcription

        print(f"[command] '{text}' → '{command_value}'")
        return command_value, last_transcription

    # Inline commands (non-action replacements only)
    result = text
    for command, replacement in VOICE_COMMANDS.items():
        if replacement.startswith("__"):
            continue
        pattern = re.compile(re.escape(command), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(replacement, result)
            print(f"[command] Inline: '{command}' → '{replacement}'")

    return result, last_transcription
