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

## Installation

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

## Setup

1. Get a free API key from [Groq Console](https://console.groq.com/keys)
2. Right-click tray icon → Settings
3. Paste your API key
4. Select your microphone
5. Click Save

## Usage

1. Place cursor where you want text
2. **Hold SHIFT** and speak (widget appears)
3. **Release SHIFT** to transcribe
4. Text appears at cursor position
5. Widget auto-hides after 2 seconds

## Tips

- Speak clearly for best results
- Works in any app (IDEs, browsers, editors)
- Right-click tray icon for settings anytime
- Say "emoji" after an emoji name to insert it (e.g., "I'm so happy happy emoji" → "I'm so happy 😊")

## Emoji Support

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

## License

MIT
