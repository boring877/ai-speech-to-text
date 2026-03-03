"""
voice_type_core.py - Shared logic for Voice Type (Full and Lite).

Pure functions and constants only: no UI, no globals, no tray, no widget references.
Both voice_type.py and voice_type_lite.py import from this module.
"""

import json
import re
from pathlib import Path

import httpx


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_FILE = Path.home() / ".voice-type-config.json"
SAMPLE_RATE = 16000
DEFAULT_FILTER_WORDS = ["thank you", "thanks", "thank you.", "thanks."]

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
    "fourty": "40",  # common misspelling / alternate transcription
    "fifty": "50",
    "sixty": "60",
    "seventy": "70",
    "eighty": "80",
    "ninety": "90",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config():
    """Load config from disk, returning a dict with all expected keys."""
    defaults = {
        "api_key": "",
        "mic_index": None,
        "hotkey": "shift",
        "accounting_mode": False,
        "accounting_comma": False,
        "casual_mode": False,
        "filter_words": DEFAULT_FILTER_WORDS,
    }
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            # Merge so new keys in defaults are always present
            defaults.update(data)
            print(f"[config] Loaded from {CONFIG_FILE}")
        except Exception as e:
            print(f"[config] Error loading: {e}")
    return defaults


def save_config(config_data):
    """Write config dict to disk."""
    CONFIG_FILE.write_text(json.dumps(config_data))


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe_with_groq(audio_path, api_key):
    """
    Transcribe audio via Groq Whisper API.
    Returns (text, error_string). On success error is None.
    """
    if not api_key:
        return None, "No API key"

    try:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        files = {"file": ("audio.wav", audio_data, "audio/wav")}
        data = {"model": "whisper-large-v3-turbo", "response_format": "json"}

        with httpx.Client(timeout=30) as client:
            response = client.post(url, headers=headers, files=files, data=data)

        if response.status_code == 200:
            return response.json().get("text"), None

        error_msg = f"HTTP {response.status_code}"
        try:
            error_detail = response.json()
            if "error" in error_detail:
                error_msg += f": {error_detail['error'].get('message', str(error_detail['error']))}"
        except Exception:
            pass
        print(f"[API] Error: {error_msg}")
        return None, error_msg

    except Exception as e:
        print(f"[API] Exception: {e}")
        return None, str(e)


# ---------------------------------------------------------------------------
# Text processing
# ---------------------------------------------------------------------------

def convert_numbers_to_digits(text):
    """Convert number words to digits (e.g. 'twenty five' → '25')."""
    result = text
    for word, digit in sorted(NUMBER_WORD_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = re.compile(
            r"(?<![a-zA-Z])" + re.escape(word) + r"(?![a-zA-Z])",
            re.IGNORECASE,
        )
        result = pattern.sub(digit, result)
    return result


def filter_text(text, filter_words):
    """
    Return empty string if text matches or contains a filter word; otherwise
    return the stripped text unchanged.
    """
    if not text:
        return ""
    result = text.strip()
    if not result or not filter_words:
        return result

    result_lower = result.lower()
    for fw in filter_words:
        fw_lower = fw.lower().strip()
        if result_lower == fw_lower:
            print(f"[filtered] Matched filter: '{fw}'")
            return ""
    # Also check substring for short texts
    if len(result) < 30:
        for fw in filter_words:
            fw_lower = fw.lower().strip()
            if fw_lower in result_lower:
                print(f"[filtered] Contains filter: '{fw}'")
                return ""
    return result


def normalize_numbers_from_api(text, accounting_comma):
    """
    Remove commas from numbers returned by the API unless comma mode is on.
    E.g. Groq may return '1,234' — strip those commas when not wanted.
    """
    if accounting_comma:
        return text

    def remove_commas(match):
        return match.group(0).replace(",", "")

    return re.sub(r"\b[\d,]+\b", remove_commas, text)


def format_number_with_commas(text):
    """Add thousands-separator commas to numbers with 4+ digits."""
    def add_commas(match):
        num = match.group(0)
        if len(num) > 3:
            return "{:,}".format(int(num))
        return num

    return re.sub(r"\b\d{4,}\b", add_commas, text)


def apply_casual_mode(text):
    """Lowercase text and strip formal punctuation for casual/texting style."""
    result = text.lower()
    result = re.sub(r"\.$", "", result)
    result = re.sub(r"\.(\s)", r"\1", result)
    result = re.sub(r"[!]{2,}", "!", result)
    result = re.sub(r"[?]{2,}", "?", result)
    result = re.sub(r",\s+", " ", result)
    return result
