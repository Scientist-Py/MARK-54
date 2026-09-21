"""
setup_google_auth.py — Interactive Google OAuth setup for JARVIS
Generates a direct clickable login link and listens for authorization on localhost:8090
"""

import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR         = Path(__file__).resolve().parent
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
TOKEN_FILE       = BASE_DIR / "config" / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
]


def main():
    print("=" * 70)
    print("🔐 JARVIS GOOGLE ACCOUNT LINKING")
    print("=" * 70)

    if not CREDENTIALS_FILE.exists():
        print(f"❌ Error: credentials.json not found in {CREDENTIALS_FILE}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    
    print("\n⏳ Opening your browser for Google Sign-In...")
    print("Please select your Google account and click 'Allow' on the permissions screen.\n")

    # Launch in default browser automatically with exact matching redirect_uri
    creds = flow.run_local_server(port=0, open_browser=True)

    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    
    print("\n" + "=" * 70)
    print("🎉 SUCCESS! Google Account successfully linked to JARVIS!")
    print(f"📁 Saved to: {TOKEN_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
