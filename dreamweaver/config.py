# dreamweaver/config.py

import os
from dotenv import load_dotenv

# Load variables from .env file (if present)
load_dotenv()

# Read Google Gemini API key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        "GOOGLE_API_KEY not found.\n"
        "Add it to a .env file like:\n"
        "    GOOGLE_API_KEY=your-key-here\n"
        "Or set it in Windows using:\n"
        '    setx GOOGLE_API_KEY "your-key-here"\n'
        "Then reopen CMD/PowerShell."
    )

# Model to use
MODEL_NAME = "gemini-2.0-flash"

# Where world JSON files are stored
BASE_STORAGE_DIR = "storage"
os.makedirs(BASE_STORAGE_DIR, exist_ok=True)

# How long before inactive players are removed (seconds)
SESSION_TIMEOUT_SECONDS = 600
