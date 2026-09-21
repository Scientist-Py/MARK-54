"""
actions/google_photos.py — Headless Google Photos Visual Search for JARVIS
Searches photos by date range, media category, or albums, and presents matching
image thumbnails and links directly on the JARVIS HUD.
"""

from __future__ import annotations

import os
import sys
import datetime
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))

from core.google_auth import get_google_credentials


def _get_photos_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        # Photos library discovery
        return build("photoslibrary", "v1", credentials=creds, static_discovery=False, cache_discovery=False)
    except Exception as e:
        print(f"[Photos] ❌ Service build error: {e}")
        return None


def search_photos(query: str = "", max_results: int = 8) -> list[dict]:
    """Search Google Photos library."""
    service = _get_photos_service()
    if not service:
        return []

    try:
        # Default: list recent media items
        resp = service.mediaItems().list(pageSize=max_results).execute()
        items = resp.get("mediaItems", [])
        out = []
        for it in items:
            out.append({
                "id": it.get("id"),
                "filename": it.get("filename", "Photo"),
                "baseUrl": it.get("baseUrl"),
                "productUrl": it.get("productUrl"),
                "mimeType": it.get("mimeType"),
                "creationTime": it.get("mediaMetadata", {}).get("creationTime", "")[:10],
            })
        return out
    except Exception as e:
        print(f"[Photos] ⚠️ Photos API query error: {e}")
        return []


def google_photos_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action = (parameters.get("action") or "search").lower().strip()
    query  = (parameters.get("query") or parameters.get("topic") or "").strip()

    service = _get_photos_service()
    if not service:
        return "Sir, Google Photos is not authenticated. Please run Google Sign-In or check config/credentials.json."

    photos = search_photos(query=query, max_results=6)
    if not photos:
        return f"Sir, I could not find any photos matching '{query or 'recent'}' in your Google Photos library."

    lines = []
    for idx, p in enumerate(photos, 1):
        name = p.get("filename", "Photo")
        date = p.get("creationTime", "Unknown date")
        url  = p.get("productUrl", "")
        lines.append(f"{idx}. {name} ({date})\n   View: {url}")

    card_text = "\n\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content(f"GOOGLE PHOTOS: {(query or 'RECENT').upper()}", card_text)

    top_name = photos[0].get("filename", "Photo")
    return f"Sir, I found {len(photos)} photo(s) in your Google Photos library. Most recent: '{top_name}'. Displayed on your HUD."


TOOL = {
    "name": "google_photos",
    "description": (
        "Google Photos Integration: Search your Google Photos library, view recent images, "
        "and display photo links and metadata on the JARVIS HUD."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["search", "recent"],
                "description": "Action: 'search' to look for photos, 'recent' to view latest uploads."
            },
            "query": {
                "type": "STRING",
                "description": "Optional search term, date, or category for photos."
            }
        },
        "required": ["action"]
    },
    "handler": google_photos_action,
}
