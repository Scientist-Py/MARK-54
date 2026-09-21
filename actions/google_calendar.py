"""
actions/google_calendar.py — Headless Google Calendar Integration for JARVIS
Fetches schedules, checks upcoming meetings, and schedules events via Google Calendar API.
"""

from __future__ import annotations

import datetime
from datetime import datetime as dt, timedelta, timezone
from pathlib import Path
import sys

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))

from core.google_auth import get_google_credentials


def _get_calendar_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Calendar] ❌ Service build error: {e}")
        return None


def _get_events(service, time_frame: str = "today", max_results: int = 10) -> str:
    now = dt.now(timezone.utc)
    tf = (time_frame or "today").lower().strip()

    if tf == "today":
        start = dt.now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
        end   = start + timedelta(days=1)
        label = "today"
    elif tf == "tomorrow":
        start = (dt.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone()
        end   = start + timedelta(days=1)
        label = "tomorrow"
    elif tf in ("this_week", "week"):
        start = dt.now().astimezone()
        end   = start + timedelta(days=7)
        label = "this week"
    else:
        # Default to next 24 hours
        start = dt.now().astimezone()
        end   = start + timedelta(days=1)
        label = time_frame

    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        if not events:
            return f"Sir, you have no scheduled calendar events for {label}."

        lines = []
        for ev in events:
            summary = ev.get("summary", "Untitled Event")
            start_raw = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            
            # Format time
            time_str = "All day"
            if "T" in start_raw:
                try:
                    parsed = dt.fromisoformat(start_raw)
                    time_str = parsed.strftime("%I:%M %p")
                except Exception:
                    time_str = start_raw

            location = ev.get("location")
            loc_str = f" at {location}" if location else ""
            lines.append(f"• {summary} at {time_str}{loc_str}")

        count = len(events)
        event_word = "event" if count == 1 else "events"
        return f"Sir, you have {count} {event_word} for {label}:\n" + "\n".join(lines)

    except Exception as e:
        return f"Could not retrieve calendar events: {e}"


def _create_event(
    service,
    summary: str,
    start_time_str: str,
    duration_minutes: int = 60,
    description: str = "",
    location: str = ""
) -> str:
    if not summary:
        return "Please specify a title or summary for the event, sir."

    now = dt.now().astimezone()

    # Parse start time (e.g. "tomorrow at 3pm", "2026-09-15 15:00", or hour string)
    event_start = now + timedelta(hours=1)  # fallback default: 1 hour from now

    if start_time_str:
        try:
            # Try ISO format
            event_start = dt.fromisoformat(start_time_str).astimezone()
        except Exception:
            # Simple heuristic matching
            st_low = start_time_str.lower()
            if "tomorrow" in st_low:
                event_start = (now + timedelta(days=1))
            if ":" in st_low:
                import re
                m = re.search(r"(\d{1,2}):(\d{2})", st_low)
                if m:
                    h, mi = int(m.group(1)), int(m.group(2))
                    if "pm" in st_low and h < 12: h += 12
                    if "am" in st_low and h == 12: h = 0
                    event_start = event_start.replace(hour=h, minute=mi, second=0)

    event_end = event_start + timedelta(minutes=duration_minutes or 60)

    event_body = {
        "summary": summary,
        "description": description or "Scheduled via JARVIS",
        "location": location or "",
        "start": {
            "dateTime": event_start.isoformat(),
        },
        "end": {
            "dateTime": event_end.isoformat(),
        },
    }

    try:
        created = service.events().insert(calendarId="primary", body=event_body).execute()
        formatted_start = event_start.strftime("%A, %b %d at %I:%M %p")
        return f"Scheduled '{summary}' for {formatted_start}, sir. Event link: {created.get('htmlLink', '')}"
    except Exception as e:
        return f"Failed to schedule the event: {e}"


def google_calendar_action(
    parameters: dict,
    player=None,
    session_memory=None,
    **kwargs
) -> str:
    action           = parameters.get("action", "get_events").lower().strip()
    time_frame       = parameters.get("time_frame", "today")
    summary          = parameters.get("summary", "")
    start_time       = parameters.get("start_time", "")
    duration_minutes = parameters.get("duration_minutes", 60)
    description      = parameters.get("description", "")
    location         = parameters.get("location", "")

    service = _get_calendar_service()
    if not service:
        msg = "Sir, Google Calendar is not authenticated. Please check your credentials."
        _log(msg, player)
        return msg

    if action in ("get_events", "list", "read", "schedule"):
        result = _get_events(service, time_frame)
    elif action in ("create_event", "add", "schedule_event", "insert"):
        result = _create_event(service, summary, start_time, duration_minutes, description, location)
    else:
        result = _get_events(service, time_frame)

    _log(result, player)

    if session_memory:
        try:
            session_memory.set_last_search(query="Google Calendar", response=result[:200])
        except Exception:
            pass

    return result


def _log(message: str, player=None) -> None:
    print(f"[Calendar] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "google_calendar",
    "description": (
        "Interacts with Google Calendar in the background to read upcoming events, check daily schedules, "
        "or create and schedule new calendar meetings."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["get_events", "create_event"],
                "description": "Whether to 'get_events' (read schedule) or 'create_event' (add new meeting)."
            },
            "time_frame": {
                "type": "STRING",
                "description": "For get_events: 'today', 'tomorrow', 'this_week', or specific date."
            },
            "summary": {
                "type": "STRING",
                "description": "For create_event: Title or topic of the meeting/event."
            },
            "start_time": {
                "type": "STRING",
                "description": "For create_event: Date/time when the event starts (e.g. '2026-09-15T15:00:00' or 'tomorrow at 3 PM')."
            },
            "duration_minutes": {
                "type": "INTEGER",
                "description": "For create_event: Duration in minutes (default 60)."
            },
            "location": {
                "type": "STRING",
                "description": "Optional location or room."
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": google_calendar_action,
}
