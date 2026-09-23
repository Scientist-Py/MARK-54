"""
actions/text_writer.py — Creative Text, Poem, Letter, and Note Writer for JARVIS
Renders formatted creative writing in the JARVIS Standalone Studio Window (Qt UI) or saves/opens file on Desktop if explicitly requested.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()

def _get_desktop_dir() -> Path:
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return Path.home() / "Desktop"


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

    # CASE A: Explicit File Creation requested ("create a file of this...")
    if save_to_desktop or filename:
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
            print(f"[TextWriter] 💾 Saved file to {target_path}")

            # Open the saved file in default OS application
            try:
                if os.name == "nt":
                    os.startfile(str(target_path))
                else:
                    subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target_path)])
            except Exception as oe:
                print(f"[TextWriter] ⚠️ Could not open file: {oe}")

            if player and hasattr(player, "write_log"):
                player.write_log(f"SYS: Saved and opened file {filename} on Desktop.")

            return f"Sir, I have created the file '{filename}' on your Desktop and opened it for you."
        except Exception as e:
            return f"Sir, creating the file failed: {e}"

    # CASE B: Viewing Text / Poem / Document (No file save requested) -> Show JARVIS Studio UI Window
    if player and hasattr(player, "show_studio"):
        try:
            player.show_studio(title, content, category)
        except Exception as e:
            print(f"[TextWriter] ⚠️ Failed to show Studio UI: {e}")
    elif player and hasattr(player, "show_content"):
        try:
            player.show_content(header_title, content)
        except Exception as e:
            print(f"[TextWriter] ⚠️ Failed to show content in UI: {e}")

    if player and hasattr(player, "write_log"):
        try:
            player.write_log(f"SYS: Displayed {category} in JARVIS Studio Window.")
        except Exception:
            pass

    return f"Sir, I have rendered the {category} '{title}' in your JARVIS Studio viewer."


TOOL = {
    "name": "text_writer",
    "description": (
        "Composes, formats, and displays poems, letters, essays, notes, summaries, or creative writing "
        "(not code) in the standalone JARVIS Studio UI window. If the user explicitly requests to 'create a file' or 'save to file', "
        "set save_to_desktop=true so it creates and opens the file in their OS text editor instead."
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
                "description": "Set to true ONLY if the user explicitly asked to create a file or save to Desktop."
            },
            "filename": {
                "type": "STRING",
                "description": "Optional custom filename (e.g. 'poem.txt')."
            }
        },
        "required": [
            "title",
            "content"
        ]
    },
    "handler": text_writer_action,
}
