# Voice Macros and Snippets Configuration
# Create your own voice commands that expand to full text

# Example: Say "my email" and it types your full email address
MACROS = {
    # Personal Info (customize these!)
    # "my email": "your.email@example.com",
    # "my phone": "+1 (555) 123-4567",
    # "my address": "123 Main Street, City, State 12345",
    
    # Common phrases
    "signature": "Best regards,\nYour Name",
    "cheers": "Cheers,\n",
    "thanks ahead": "Thanks in advance!",
    
    # Code snippets
    "todo comment": "// TODO: ",
    "fixme comment": "// FIXME: ",
    "note comment": "// NOTE: ",
    
    # Common responses
    "let me check": "Let me check on that and get back to you.",
    "sounds good": "Sounds good, let me know if you need anything else!",
    "will do": "Will do!",
    
    # URLs (customize these!)
    # "my website": "https://yourwebsite.com",
    # "my linkedin": "https://linkedin.com/in/yourprofile",
    # "my github": "https://github.com/yourusername",
    
    # Date/time placeholders (these get replaced dynamically)
    "today date": "{{DATE}}",
    "now time": "{{TIME}}",
    "date time": "{{DATETIME}}",
}

# These macros are loaded from config file if it exists
# File location: ~/.voice-type-macros.json
