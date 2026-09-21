"""
core/google_auth.py — Unified Google OAuth2 Manager for JARVIS (Calendar + Gmail)
Handles one-time authentication, local token caching (config/token.json), and silent background refresh.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR         = get_base_dir()
CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
TOKEN_FILE       = BASE_DIR / "config" / "token.json"

# Unified Scopes for Google Calendar, Gmail, Contacts, Drive, Sheets, Tasks, and Photos
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/photoslibrary.readonly",
]


def get_google_credentials() -> Credentials | None:
    """Return valid Google OAuth2 credentials.
    On first run, opens local browser once to authenticate.
    Subsequent runs load config/token.json and refresh silently in the background.
    """
    if not CREDENTIALS_FILE.exists():
        print(f"[GoogleAuth] ❌ Missing {CREDENTIALS_FILE}. Place your OAuth credentials JSON here.")
        return None

    creds = None
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except Exception as e:
            print(f"[GoogleAuth] ⚠️ Token load error: {e}")
            creds = None

    # If credentials don't exist or are invalid
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("[GoogleAuth] 🔄 Silently refreshing expired Google token in background...")
                creds.refresh(Request())
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                return creds
            except Exception as e:
                print(f"[GoogleAuth] ⚠️ Token refresh failed: {e}. Re-authenticating...")

        # One-time user consent flow
        try:
            print("[GoogleAuth] Opening browser for Google Sign-In...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
            TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            print("[GoogleAuth] Authentication successful! Saved to token.json.")
        except Exception as e:
            print(f"[GoogleAuth] Authentication failed: {e}")
    return creds


if __name__ == "__main__":
    print("=" * 60)
    print("🔐 JARVIS Google OAuth Authentication Setup")
    print("=" * 60)
    creds = get_google_credentials()
    if creds and creds.valid:
        print("\n🎉 Google Account successfully linked to JARVIS!")
        print("Calendar and Gmail are now ready for headless background execution.")
    else:
        print("\n❌ Setup incomplete. Please check the logs above.")
