"""
actions/text_writer.py — Creative Text, Poem, Letter, and Note Writer for JARVIS
Renders formatted writing on the React Studio UI and the HUD Content Panel, with option to save to Desktop.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path

def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
DRAFT_FILE = BASE_DIR / "config" / "active_draft.json"

def _get_desktop_dir() -> Path:
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return Path.home() / "Desktop"


def _open_react_studio(draft_data: dict) -> None:
    """Open the React Studio UI in browser with the pre-filled poem/text."""
    try:
        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_FILE.write_text(json.dumps(draft_data, indent=2), encoding="utf-8")
        
        params = urllib.parse.urlencode({
            "type": "studio",
            "title": draft_data.get("title", ""),
            "content": draft_data.get("content", ""),
            "category": draft_data.get("category", "poem"),
        })
        url = f"http://localhost:8000/compose?{params}"
        print(f"[TextStudio] 🌐 Opening React Studio UI: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"[TextStudio] ⚠️ Failed to launch browser: {e}")


def text_writer_action(
    parameters: dict,
    player=None,
    session_memory=None,
    **kwargs
) -> str:
    title           = (parameters.get("title") or "Draft").strip()
    content         = (parameters.get("content") or "").strip()
    category        = (parameters.get("category") or "poem").strip().lower()
    save_to_desktop = bool(parameters.get("save_to_desktop", False))
    filename        = (parameters.get("filename") or "").strip()

    if not content:
        return "Sir, please provide the text or content you would like me to write."

    header_title = f"{category.upper()}: {title}"
    
    # 1. Open React Studio UI
    draft_data = {
        "type": "studio",
        "title": title,
        "content": content,
        "category": category,
    }
    _open_react_studio(draft_data)

    # 2. Also display on HUD Content Panel
    if player and hasattr(player, "show_content"):
        try:
            player.show_content(header_title, content)
        except Exception as e:
            print(f"[TextWriter] ⚠️ Failed to show content in UI: {e}")

    saved_msg = ""
    # 3. Save to Desktop if requested
    if save_to_desktop:
        try:
            desktop = _get_desktop_dir()
            if not filename:
                safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", title.lower())[:32].strip("_") or "written_piece"
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{safe_name}_{ts}.txt"
            elif not filename.endswith(".txt"):
                filename = f"{filename}.txt"

            target_path = desktop / filename
            target_path.write_text(f"{title}\n" + "=" * len(title) + f"\n\n{content}\n", encoding="utf-8")
            saved_msg = f" and saved a copy to your Desktop as {filename}"
            print(f"[TextWriter] 💾 Saved file to {target_path}")
        except Exception as e:
            saved_msg = f", though saving to Desktop failed: {e}"

    if player and hasattr(player, "write_log"):
        try:
            player.write_log(f"SYS: Displayed {category} on React Studio & HUD{saved_msg}.")
        except Exception:
            pass

    return f"Sir, I have opened the {category} '{title}' in your studio workspace{saved_msg}."


TOOL = {
    "name": "text_writer",
    "description": (
        "Composes, formats, and displays poems, letters, essays, notes, summaries, or creative writing "
        "(not code) in a clean React Studio UI and HUD screen for review, with an option to save to Desktop."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "title": {
                "type": "STRING",
                "description": "Title or heading of the piece (e.g., 'Starlight Reverie', 'Formal Request Letter', 'Meeting Takeaways')."
            },
            "content": {
                "type": "STRING",
                "description": "The full text / poem / letter content formatted with proper line breaks."
            },
            "category": {
                "type": "STRING",
                "enum": ["poem", "letter", "note", "essay", "draft", "story"],
                "description": "The category of text being written."
            },
            "save_to_desktop": {
                "type": "BOOLEAN",
                "description": "Set to true if the user asked to save the text to a file on their Desktop."
            },
            "filename": {
                "type": "STRING",
                "description": "Optional custom filename (e.g. 'poem.txt'). Defaults to a title-based filename."
            }
        },
        "required": [
            "title",
            "content"
        ]
    },
    "handler": text_writer_action,
}
