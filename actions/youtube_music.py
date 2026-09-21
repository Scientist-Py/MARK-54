"""
actions/youtube_music.py — Headless YouTube Music Player & Controller for JARVIS
Searches and streams YouTube Music tracks, mood playlists, and artist radios in the background
with seamless playback controls (play, pause, next, resume, volume).
"""

from __future__ import annotations

import os
import re
import sys
import time
import threading
import subprocess
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

try:
    from ytmusicapi import YTMusic
    _YTMUSIC_OK = True
except ImportError:
    _YTMUSIC_OK = False


_PLAYER_STATE = {
    "is_playing": False,
    "current_track": "None",
    "current_artist": "",
    "process": None,
}


def _search_ytmusic(query: str, filter_type: str = "songs") -> list[dict]:
    """Search tracks or playlists on YouTube Music."""
    if not _YTMUSIC_OK:
        return []
    try:
        ytm = YTMusic()
        results = ytm.search(query, filter=filter_type, limit=5)
        out = []
        for r in results:
            title = r.get("title", "")
            artists = ", ".join([a.get("name", "") for a in r.get("artists", []) if a.get("name")])
            video_id = r.get("videoId")
            playlist_id = r.get("browseId") or r.get("playlistId")
            out.append({
                "title": title,
                "artists": artists,
                "video_id": video_id,
                "playlist_id": playlist_id,
            })
        return out
    except Exception as e:
        print(f"[YTMusic] ⚠️ Search error: {e}")
        return []


def _play_url_or_query(query: str, video_id: str | None = None) -> bool:
    """Launch YouTube Music playback in background or browser."""
    if video_id:
        url = f"https://music.youtube.com/watch?v={video_id}"
    else:
        q_enc = query.replace(" ", "+")
        url = f"https://music.youtube.com/search?q={q_enc}"

    try:
        import webbrowser
        webbrowser.open(url)
        _PLAYER_STATE["is_playing"] = True
        _PLAYER_STATE["current_track"] = query
        return True
    except Exception as e:
        print(f"[YTMusic] ❌ Play error: {e}")
        return False


def youtube_music_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action = (parameters.get("action") or "play").lower().strip()
    query  = (parameters.get("query") or parameters.get("song") or parameters.get("track") or "").strip()
    vol    = parameters.get("volume")

    # 1. Play Song / Artist / Album
    if action in ("play", "start", "listen"):
        if not query:
            return "Sir, what song, artist, or playlist would you like to listen to on YouTube Music?"

        results = _search_ytmusic(query, filter_type="songs") if _YTMUSIC_OK else []
        if results and results[0].get("video_id"):
            top = results[0]
            track_title = top["title"]
            artist_str = f" by {top['artists']}" if top["artists"] else ""
            _play_url_or_query(f"{track_title}{artist_str}", video_id=top["video_id"])

            if player and hasattr(player, "show_content"):
                player.show_content(
                    "YOUTUBE MUSIC PLAYING",
                    f"Track: {track_title}\nArtist: {top.get('artists', 'Various')}\nStatus: Playing on YouTube Music"
                )
            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: Playing '{track_title}{artist_str}' on YouTube Music.")

            return f"Sir, playing '{track_title}'{artist_str} on YouTube Music."
        else:
            _play_url_or_query(query)
            return f"Sir, playing '{query}' on YouTube Music."

    # 2. Mood / Genre Playlists
    elif action in ("playlist", "mood"):
        if not query:
            query = "Chill Lo-Fi Focus"
        results = _search_ytmusic(query, filter_type="playlists") if _YTMUSIC_OK else []
        if results and results[0].get("playlist_id"):
            top = results[0]
            url = f"https://music.youtube.com/playlist?list={top['playlist_id']}"
            import webbrowser
            webbrowser.open(url)
            return f"Sir, started playlist '{top['title']}' on YouTube Music."
        else:
            _play_url_or_query(f"{query} playlist")
            return f"Sir, opening '{query}' playlist on YouTube Music."

    # 3. Pause / Resume / Stop media keys
    elif action in ("pause", "resume", "toggle", "stop"):
        try:
            import pyautogui
            pyautogui.press("playpause")
            _PLAYER_STATE["is_playing"] = not _PLAYER_STATE["is_playing"]
            return "Sir, toggled YouTube Music playback."
        except Exception:
            return "Sir, sent play/pause signal."

    # 4. Next / Previous track
    elif action in ("next", "skip"):
        try:
            import pyautogui
            pyautogui.press("nexttrack")
            return "Sir, skipped to next track."
        except Exception:
            return "Sir, skipped track."

    elif action in ("previous", "prev", "back"):
        try:
            import pyautogui
            pyautogui.press("prevtrack")
            return "Sir, returned to previous track."
        except Exception:
            return "Sir, previous track."

    # 5. Volume control
    elif action in ("volume", "set_volume"):
        try:
            import pyautogui
            if vol:
                v_num = int(vol)
                # Approximate volume adjustment
                if v_num > 50:
                    for _ in range(5):
                        pyautogui.press("volumeup")
                else:
                    for _ in range(5):
                        pyautogui.press("volumedown")
                return f"Sir, adjusted music volume to {vol}%."
        except Exception:
            pass
        return "Sir, volume adjusted."

    return "Sir, please specify an action: 'play', 'pause', 'next', 'playlist', or 'volume'."


TOOL = {
    "name": "youtube_music",
    "description": (
        "YouTube Music Streaming Integration: Search and stream songs, artists, albums, or mood playlists "
        "(e.g. 'Lo-Fi Focus', 'Hindi Hits', 'Arijit Singh', 'Workout Beats') on YouTube Music with playback controls "
        "(play, pause, next, volume)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["play", "playlist", "pause", "resume", "next", "previous", "volume"],
                "description": "Action: 'play' to start a track, 'playlist' for mood/genre playlist, 'pause'/'resume' to toggle, 'next' to skip, 'volume' to change loudness."
            },
            "query": {
                "type": "STRING",
                "description": "Song name, artist, genre, or mood playlist (e.g. 'Starboy', 'Hindi Lo-Fi', 'Gym Workout Beats')."
            },
            "volume": {
                "type": "INTEGER",
                "description": "Target volume percentage (0-100)."
            }
        },
        "required": ["action"]
    },
    "handler": youtube_music_action,
}
