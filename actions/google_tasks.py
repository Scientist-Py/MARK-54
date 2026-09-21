"""
actions/google_tasks.py — Headless Google Tasks Integration for JARVIS
Fetches pending to-do tasks, adds new tasks with due dates, and marks tasks as completed.
Synchronized live with Android/iOS Google Tasks and Google Calendar.
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


def _get_tasks_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("tasks", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Tasks] ❌ Service build error: {e}")
        return None


def list_tasks(show_completed: bool = False, max_results: int = 15) -> list[dict]:
    """List tasks from the default task list."""
    service = _get_tasks_service()
    if not service:
        return []
    try:
        # Get primary/default tasklist
        tasklists = service.tasklists().list(maxResults=10).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return []
        primary_list_id = lists[0]["id"]

        resp = service.tasks().list(
            tasklist=primary_list_id,
            showCompleted=show_completed,
            showHidden=show_completed,
            maxResults=max_results,
        ).execute()

        items = resp.get("items", [])
        out = []
        for t in items:
            out.append({
                "id": t.get("id"),
                "title": t.get("title", "Untitled Task"),
                "notes": t.get("notes", ""),
                "status": t.get("status", "needsAction"),
                "due": t.get("due", "")[:10] if t.get("due") else None,
            })
        return out
    except Exception as e:
        print(f"[Tasks] ❌ List error: {e}")
        return []


def add_task(title: str, notes: str = "", due_date: str | None = None) -> dict | None:
    """Add a new task to the primary Google Tasks list."""
    service = _get_tasks_service()
    if not service:
        return None
    try:
        tasklists = service.tasklists().list(maxResults=10).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return None
        list_id = lists[0]["id"]

        task_body = {"title": title}
        if notes:
            task_body["notes"] = notes
        if due_date:
            # Format RFC3339
            try:
                dt = datetime.datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                task_body["due"] = dt.strftime("%Y-%m-%dT00:00:00.000Z")
            except Exception:
                task_body["due"] = f"{due_date}T00:00:00.000Z"

        created = service.tasks().insert(tasklist=list_id, body=task_body).execute()
        return created
    except Exception as e:
        print(f"[Tasks] ❌ Add error: {e}")
        return None


def complete_task(task_title_or_id: str) -> bool:
    """Mark a task as completed."""
    service = _get_tasks_service()
    if not service:
        return False
    try:
        tasklists = service.tasklists().list(maxResults=10).execute()
        lists = tasklists.get("items", [])
        if not lists:
            return False
        list_id = lists[0]["id"]

        # Find matching task
        tasks = service.tasks().list(tasklist=list_id, showCompleted=False).execute().get("items", [])
        target_id = None
        target_task = None
        for t in tasks:
            if t.get("id") == task_title_or_id or task_title_or_id.lower() in t.get("title", "").lower():
                target_id = t.get("id")
                target_task = t
                break

        if not target_id:
            return False

        target_task["status"] = "completed"
        service.tasks().update(tasklist=list_id, task=target_id, body=target_task).execute()
        return True
    except Exception as e:
        print(f"[Tasks] ❌ Complete error: {e}")
        return False


def google_tasks_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action   = (parameters.get("action") or "list").lower().strip()
    title    = (parameters.get("title") or parameters.get("task") or "").strip()
    notes    = (parameters.get("notes") or "").strip()
    due_date = (parameters.get("due_date") or parameters.get("due") or "").strip()

    service = _get_tasks_service()
    if not service:
        return "Sir, Google Tasks is not authenticated. Please run Google Sign-In or check config/credentials.json."

    # 1. List tasks
    if action in ("list", "show", "pending", "get"):
        tasks = list_tasks(show_completed=False, max_results=12)
        if not tasks:
            return "Sir, you have no pending tasks in your Google Tasks list."

        lines = []
        for idx, t in enumerate(tasks, 1):
            due = f" (Due: {t['due']})" if t.get("due") else ""
            note = f" — {t['notes']}" if t.get("notes") else ""
            lines.append(f"{idx}. [ ] {t['title']}{due}{note}")

        card_text = "\n".join(lines)
        if player and hasattr(player, "show_content"):
            player.show_content("GOOGLE TASKS", card_text)

        summary_titles = ", ".join([t['title'] for t in tasks[:3]])
        more_str = f" and {len(tasks)-3} more" if len(tasks) > 3 else ""
        return f"Sir, you have {len(tasks)} pending task(s): {summary_titles}{more_str}. Displayed on your HUD."

    # 2. Add task
    elif action in ("add", "create", "new"):
        if not title:
            return "Sir, please provide the task title or description to add."
        res = add_task(title=title, notes=notes, due_date=due_date or None)
        if not res:
            return f"Sir, failed to add task '{title}' to Google Tasks."

        if player and hasattr(player, "write_log"):
            player.write_log(f"SYS: Added task to Google Tasks: {title}")

        return f"Sir, I have added '{title}' to your Google Tasks list."

    # 3. Complete task
    elif action in ("complete", "done", "finish", "check"):
        if not title:
            return "Sir, please specify which task you have completed."
        ok = complete_task(title)
        if ok:
            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: Completed task: {title}")
            return f"Sir, marked '{title}' as completed in Google Tasks."
        return f"Sir, could not find any active task matching '{title}' to complete."

    return "Sir, please specify an action: 'list', 'add', or 'complete'."


TOOL = {
    "name": "google_tasks",
    "description": (
        "Google Tasks Integration: View pending to-do tasks, add new tasks with due dates, "
        "and mark tasks as completed. Synced live with Android/iOS phone and Google Calendar."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["list", "add", "complete"],
                "description": "Action: 'list' to view pending tasks, 'add' to create a new task, 'complete' to mark task as done."
            },
            "title": {
                "type": "STRING",
                "description": "Task description or title (e.g. 'Review code', 'Buy groceries', 'Call Puneet')."
            },
            "notes": {
                "type": "STRING",
                "description": "Optional notes or details for the task."
            },
            "due_date": {
                "type": "STRING",
                "description": "Optional due date in YYYY-MM-DD format (e.g. '2026-09-20')."
            }
        },
        "required": ["action"]
    },
    "handler": google_tasks_action,
}
