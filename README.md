# AI Speech to Text for AI Agency

Hold **SHIFT** to speak, release to type. Fast, accurate voice-to-text using Groq Whisper API.

## Features

- Hold SHIFT to record - Release to transcribe and type
- Fast transcription - Groq Whisper API (~0.5s)
- High accuracy - Whisper large-v3-turbo model
- System tray icon - Right-click for settings
- Auto-hide widget - Only shows when recording
- Easy settings - Mic picker, API key input in UI
- Privacy focused - Audio processed by Groq, not stored

### New in v1.2.0

- **Accounting Mode** - Converts spoken numbers to digits (e.g., "one hundred twenty three" → "123")
- **Comma Formatting** - Optional commas in large numbers (e.g., "1,234,567")
- **Casual Mode** - Lowercase output with informal punctuation
- **Filter Words** - Block unwanted phrases (e.g., "thank you" when nothing said)
- **Blue Theme** - Modern dark blue UI
- **Custom Hotkeys** - Change push-to-talk key in settings
- **Emoji Voice Commands** - Say "happy emoji" to insert 😊 (100+ emojis supported)

## Two Versions Available

| Version | File | Description |
|---------|------|-------------|
| **Full** | `VoiceType.exe` | All features, system tray, emoji support |
| **Lite** | `VoiceTypeLite.exe` | Optimized for older/slower computers |

### Lite Version Differences
- Uses `distil-whisper-large-v3-en` model (faster)
- No system tray icon (less memory)
- No emoji conversion
- Simpler UI
- Smaller audio chunks
- Shares settings with Full version

## Installation

### Option 1: Pre-built Executables

**Windows:**
- Download `VoiceType.exe` (or `VoiceTypeLite.exe` for older computers) from the `dist` folder
- Double-click to run (no installation needed)

**macOS:**
- Download `VoiceType.pkg`
- Double-click it
- Click "Continue" then "Install"
- Done! VoiceType is in your Applications folder

### Option 2: Run from Source

1. **Clone the repo**
   ```bash
   git clone https://github.com/yourusername/ai-speech-to-text.git
   cd ai-speech-to-text
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   ```

3. **Activate venv**
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

4. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

5. **Run**
   ```bash
   python voice_type.py
   ```
   
   Or on Windows, just double-click `run.bat`

## Building from Source

### Windows
```bash
pip install pyinstaller
pyinstaller VoiceType.spec --noconfirm
```
The executable will be created at `dist/VoiceType.exe`

### macOS
```bash
chmod +x build-mac.sh
./build-mac.sh
```
This creates:
- `dist/VoiceType.app` - The application bundle
- `dist/VoiceType.pkg` - PKG installer (share this file)

**Note:** You must build on the target platform. Windows builds only work on Windows, Mac builds only work on Mac.

## Setup

1. Get a free API key from [Groq Console](https://console.groq.com/keys)
2. Right-click tray icon → Settings (or settings open automatically on first run)
3. Paste your API key
4. Select your microphone
5. Configure features (Accounting Mode, Casual Mode, Filter Words)
6. Click Save

## Usage

1. Place cursor where you want text
2. **Hold SHIFT** and speak (widget appears)
3. **Release SHIFT** to transcribe
4. Text appears at cursor position
5. Widget auto-hides after 2 seconds

## Features in Detail

### Accounting Mode
When enabled, converts spoken number words to digits:
- "one" → "1"
- "twenty five" → "25"
- "one hundred" → "100"

### Comma Formatting
When enabled with Accounting Mode, adds commas to large numbers:
- "1000000" → "1,000,000"

### Casual Mode
When enabled, outputs lowercase text with informal punctuation:
- No capitalization
- Periods removed
- Multiple punctuation reduced

### Filter Words
Block unwanted phrases from being typed. Useful for blocking:
- "thank you" (common hallucination when nothing said)
- "thanks"
- Any custom words

Enter as comma-separated list in settings.

## Tips

- Speak clearly for best results
- Works in any app (IDEs, browsers, editors)
- Right-click tray icon for settings anytime (Full version only)
- Say "emoji" after an emoji name to insert it (Full version only)

## Emoji Support (Full Version Only)

Speak emoji names to insert actual emojis! Just say the emoji name followed by "emoji":

| Say This | Get This |
|----------|----------|
| "happy emoji" | 😊 |
| "sad emoji" | 😢 |
| "angry emoji" | 😠 |
| "laughing emoji" | 😂 |
| "heart emoji" | ❤️ |
| "fire emoji" | 🔥 |
| "thumbs up emoji" | 👍 |
| "thinking emoji" | 🤔 |
| "party emoji" | 🎉 |
| "rocket emoji" | 🚀 |

**Examples:**
- "That's awesome fire emoji" → "That's awesome 🔥"
- "Great job thumbs up emoji" → "Great job 👍"
- "I'm confused thinking emoji" → "I'm confused 🤔"

Over 100+ emojis supported including emotions, animals, food, gestures, and more!

## Requirements

- Python 3.8+
- Microphone
- Internet connection
- Groq API key (free tier available)

## Security

- API keys are stored locally in `~/.voice-type-config.json`
- No data is sent anywhere except Groq API for transcription
- Audio is processed in real-time and not saved to disk permanently

## Version History

- **v1.2.0** - Accounting mode, casual mode, filter words, blue theme, Lite version
- **v1.1.0** - Emoji support, custom hotkeys
- **v1.0.0** - Initial release

## License

MIT