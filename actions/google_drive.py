"""
actions/google_drive.py — Headless Google Drive & Sheets Integration for JARVIS
Searches Drive files, uploads local files/screenshots with shareable links,
and reads/appends rows to Google Spreadsheets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
import datetime

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


def _get_drive_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Drive] ❌ Service build error: {e}")
        return None


def _get_sheets_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("sheets", "v4", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Sheets] ❌ Service build error: {e}")
        return None


def search_drive(query: str, max_results: int = 10) -> list[dict]:
    """Search files on Drive by name or text."""
    service = _get_drive_service()
    if not service:
        return []

    q_escaped = query.replace("'", "\\'")
    # Search by name contains or fullText contains
    q_filter = f"name contains '{q_escaped}' and trashed = false"

    try:
        resp = service.files().list(
            q=q_filter,
            pageSize=max_results,
            fields="files(id, name, mimeType, webViewLink, createdTime, modifiedTime, size)",
            orderBy="modifiedTime desc",
        ).execute()
        return resp.get("files", [])
    except Exception as e:
        print(f"[Drive] ⚠️ Search error: {e}")
        # Fallback to general search
        try:
            resp = service.files().list(
                pageSize=max_results,
                fields="files(id, name, mimeType, webViewLink, modifiedTime)",
                orderBy="modifiedTime desc",
            ).execute()
            return [f for f in resp.get("files", []) if query.lower() in f.get("name", "").lower()]
        except Exception:
            return []


def upload_to_drive(file_path: str, folder_id: str | None = None) -> dict | None:
    """Upload a local file to Google Drive and return file metadata + web link."""
    service = _get_drive_service()
    if not service:
        return None

    p = Path(file_path).resolve()
    if not p.exists():
        print(f"[Drive] ❌ File not found: {p}")
        return None

    try:
        from googleapiclient.http import MediaFileUpload
        file_metadata = {"name": p.name}
        if folder_id:
            file_metadata["parents"] = [folder_id]

        media = MediaFileUpload(str(p), resumable=True)
        file_obj = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
        ).execute()

        # Set permission to anyone with link viewable (optional)
        try:
            service.permissions().create(
                fileId=file_obj.get("id"),
                body={"role": "reader", "type": "anyone"},
            ).execute()
        except Exception:
            pass

        return file_obj
    except Exception as e:
        print(f"[Drive] ❌ Upload failed: {e}")
        return None


def append_to_sheet(spreadsheet_id: str, row_values: list, sheet_range: str = "Sheet1!A:Z") -> bool:
    """Append a row to Google Sheets."""
    service = _get_sheets_service()
    if not service:
        return False
    try:
        body = {"values": [row_values]}
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        ).execute()
        return True
    except Exception as e:
        print(f"[Sheets] ❌ Append error: {e}")
        return False


def read_sheet(spreadsheet_id: str, sheet_range: str = "Sheet1!A1:Z50") -> list[list]:
    """Read cell rows from Google Sheets."""
    service = _get_sheets_service()
    if not service:
        return []
    try:
        resp = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=sheet_range,
        ).execute()
        return resp.get("values", [])
    except Exception as e:
        print(f"[Sheets] ❌ Read error: {e}")
        return []


def google_drive_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action         = (parameters.get("action") or "search").lower().strip()
    query          = (parameters.get("query") or parameters.get("name") or "").strip()
    file_path      = (parameters.get("file_path") or "").strip()
    spreadsheet_id = (parameters.get("spreadsheet_id") or "").strip()
    sheet_data     = parameters.get("data")

    # 1. Search Google Drive
    if action in ("search", "find", "list"):
        if not query:
            return "Sir, please specify what file or folder you would like to search for in your Google Drive."
        files = search_drive(query, max_results=8)
        if not files:
            return f"Sir, I could not find any files matching '{query}' in your Google Drive."

        lines = []
        for idx, f in enumerate(files, 1):
            name = f.get("name", "Untitled")
            link = f.get("webViewLink", "")
            mod  = f.get("modifiedTime", "")[:10]
            lines.append(f"{idx}. {name} (Modified: {mod})\n   Link: {link}")

        card_text = "\n\n".join(lines)
        if player and hasattr(player, "show_content"):
            player.show_content(f"GOOGLE DRIVE: {query.upper()}", card_text)

        top_file = files[0]
        return f"Sir, I found {len(files)} file(s) matching '{query}'. Top result: {top_file.get('name')}. Details are on your HUD."

    # 2. Upload file to Google Drive
    elif action in ("upload", "upload_file", "save_to_drive"):
        if not file_path:
            return "Sir, please provide the local file path to upload to Google Drive."
        
        target = Path(file_path).resolve()
        if not target.exists():
            return f"Sir, the file at '{file_path}' does not exist."

        res = upload_to_drive(str(target))
        if not res:
            return f"Sir, failed to upload '{target.name}' to Google Drive. Please check connection and permissions."

        link = res.get("webViewLink") or "Drive link ready"
        if player and hasattr(player, "show_content"):
            player.show_content(
                f"DRIVE UPLOAD: {target.name.upper()}",
                f"File: {target.name}\nStatus: Uploaded Successfully\n\nShareable Link:\n{link}"
            )

        return f"Sir, '{target.name}' has been uploaded to your Google Drive. The shareable link is displayed on your HUD."

    # 3. Append to Google Sheets
    elif action in ("append_sheet", "log_data", "write_sheet"):
        if not spreadsheet_id:
            return "Sir, please provide the Google Spreadsheet ID to log data."
        
        values = []
        if isinstance(sheet_data, list):
            values = sheet_data
        elif isinstance(sheet_data, str):
            values = [s.strip() for s in sheet_data.split(",")]
        else:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            values = [now_str, query or "Log Entry"]

        ok = append_to_sheet(spreadsheet_id, values)
        if ok:
            return "Sir, data has been appended to your Google Spreadsheet."
        return "Sir, failed to append data to the spreadsheet. Please verify Spreadsheet ID and permissions."

    # 4. Read from Google Sheets
    elif action in ("read_sheet", "get_sheet_data"):
        if not spreadsheet_id:
            return "Sir, please provide the Google Spreadsheet ID to read."
        
        range_str = query or "Sheet1!A1:Z20"
        rows = read_sheet(spreadsheet_id, sheet_range=range_str)
        if not rows:
            return "Sir, no data found in the specified sheet range."

        sheet_text = "\n".join([" | ".join(row) for row in rows[:15]])
        if player and hasattr(player, "show_content"):
            player.show_content("GOOGLE SHEETS DATA", sheet_text)

        return f"Sir, retrieved {len(rows)} row(s) from your spreadsheet. The data is displayed on your HUD."

    return "Sir, please specify an action: 'search', 'upload', 'append_sheet', or 'read_sheet'."


TOOL = {
    "name": "google_drive",
    "description": (
        "Google Drive & Sheets Integration: Search files and documents in Google Drive, "
        "upload local files/screenshots with instant shareable links, and read or log rows into Google Spreadsheets."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["search", "upload", "append_sheet", "read_sheet"],
                "description": "Action: 'search' for files on Drive, 'upload' to save a local file, 'append_sheet' to log a row in Sheets, 'read_sheet' to view spreadsheet data."
            },
            "query": {
                "type": "STRING",
                "description": "File search keyword (e.g. 'invoice', 'resume', 'budget') or Sheets cell range."
            },
            "file_path": {
                "type": "STRING",
                "description": "Local absolute path of file to upload to Drive."
            },
            "spreadsheet_id": {
                "type": "STRING",
                "description": "Google Spreadsheet ID for reading/writing sheet rows."
            },
            "data": {
                "type": "STRING",
                "description": "Comma-separated row values to append to the spreadsheet."
            }
        },
        "required": ["action"]
    },
    "handler": google_drive_action,
}
