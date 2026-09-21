"""
actions/phone_call.py — Outbound Phone and WhatsApp Calling for JARVIS
Supports:
1. Regular Phone Calls (Default) via Windows 'tel:' protocol handler / Microsoft Phone Link.
2. WhatsApp Calls (Voice & Video) via WhatsApp Desktop automation & URI protocol.
3. Automatic Google Contacts lookup for contact names.
"""

from __future__ import annotations

import os
import re
import sys
import time
import subprocess
import webbrowser
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
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False


def _clean_phone_number(number: str) -> str:
    """Normalize and format phone number for dialing."""
    if not number:
        return ""
    has_plus = number.strip().startswith("+")
    digits = re.sub(r"[^\d]", "", number)
    if not digits:
        return ""
    
    if len(digits) == 10 and not has_plus:
        return f"+91{digits}"
    if has_plus:
        return f"+{digits}"
    return digits


def _lookup_contact_number(target: str) -> tuple[str, str]:
    """
    Look up contact in Google Contacts if target is a name.
    Returns: (resolved_name, clean_phone_number)
    """
    target_clean = target.strip()
    digits = re.sub(r"[^\d]", "", target_clean)
    
    if len(digits) >= 7 and (len(digits) / max(len(target_clean), 1) > 0.6):
        return target_clean, _clean_phone_number(target_clean)

    try:
        from actions.google_contacts import search_contacts
        contacts = search_contacts(target_clean, max_results=5)
        if contacts:
            for c in contacts:
                phones = c.get("phones", [])
                if phones:
                    resolved_name = c.get("name") or target_clean
                    return resolved_name, _clean_phone_number(phones[0])
            resolved_name = contacts[0].get("name") or target_clean
            return resolved_name, ""
    except Exception as e:
        print(f"[PhoneCall] ⚠️ Google Contacts lookup error: {e}")

    return target_clean, ""


def make_phone_call(target: str, player=None) -> str:
    """
    Place a cellular/standard phone call via Windows 'tel:' protocol / Microsoft Phone Link.
    """
    resolved_name, phone_number = _lookup_contact_number(target)

    if not phone_number:
        msg = f"Sir, I could not find a phone number for '{target}' in your Google Contacts. Please specify the phone number."
        if player and hasattr(player, "show_content"):
            player.show_content("PHONE CALL FAILED", f"Contact: {target}\nError: No phone number found in Google Contacts.")
        return msg

    print(f"[PhoneCall] 📞 Initiating cellular call to {resolved_name} ({phone_number})...")

    try:
        if sys.platform == "win32":
            os.startfile(f"tel:{phone_number}")
        else:
            webbrowser.open(f"tel:{phone_number}")
    except Exception as e:
        try:
            subprocess.Popen(["cmd", "/c", "start", f"tel:{phone_number}"], shell=True)
        except Exception as e2:
            print(f"[PhoneCall] ⚠️ Failed to trigger tel: protocol: {e2}")
            return f"Sir, there was an issue launching the phone dialer: {e2}"

    if player and hasattr(player, "show_content"):
        player.show_content(
            f"DIALING: {resolved_name.upper()}",
            f"Target: {resolved_name}\nNumber: {phone_number}\nService: Cellular (Phone Link / tel:)\nStatus: Calling..."
        )

    return f"Sir, placing a phone call to {resolved_name} at {phone_number} now."


def make_whatsapp_call(target: str, call_type: str = "voice", player=None) -> str:
    """
    Place a WhatsApp voice or video call via WhatsApp Desktop.
    """
    resolved_name, phone_number = _lookup_contact_number(target)
    is_video = "video" in call_type.lower()
    call_mode_str = "video call" if is_video else "voice call"

    print(f"[PhoneCall] 💬 Initiating WhatsApp {call_mode_str} to {resolved_name}...")

    launched = False
    if phone_number:
        clean_digits = re.sub(r"[^\d]", "", phone_number)
        uri = f"whatsapp://send?phone={clean_digits}"
        try:
            if sys.platform == "win32":
                os.startfile(uri)
            else:
                webbrowser.open(uri)
            launched = True
            time.sleep(2.0)
        except Exception as e:
            print(f"[PhoneCall] ⚠️ whatsapp URI open error: {e}")

    if not launched and _PYAUTOGUI:
        try:
            if sys.platform == "win32":
                os.system("start whatsapp:")
            time.sleep(1.5)
            
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            pyautogui.hotkey("ctrl", "a")
            pyautogui.press("backspace")
            time.sleep(0.2)
            
            query_to_type = target if not phone_number else phone_number
            pyautogui.write(query_to_type, interval=0.03)
            time.sleep(1.0)
            pyautogui.press("enter")
            time.sleep(1.0)
            launched = True
        except Exception as e:
            print(f"[PhoneCall] ⚠️ WhatsApp UI automation error: {e}")

    if _PYAUTOGUI:
        time.sleep(1.0)
        try:
            if is_video:
                pyautogui.hotkey("ctrl", "shift", "v")
            else:
                pyautogui.hotkey("ctrl", "shift", "c")
        except Exception as e:
            print(f"[PhoneCall] ⚠️ Call shortcut error: {e}")

    if player and hasattr(player, "show_content"):
        player.show_content(
            f"WHATSAPP {call_mode_str.upper()}: {resolved_name.upper()}",
            f"Target: {resolved_name}\nNumber: {phone_number or 'Contact Name'}\nService: WhatsApp Desktop\nType: {call_mode_str.capitalize()}\nStatus: Ringing..."
        )

    return f"Sir, placing a WhatsApp {call_mode_str} to {resolved_name} now."


def phone_call_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    """
    Main dispatcher for phone_call action.
    parameters:
      - target: Name of contact or phone number
      - platform: 'phone' (default) or 'whatsapp'
      - call_type: 'voice' (default) or 'video'
    """
    target = (parameters.get("target") or parameters.get("contact") or parameters.get("name") or "").strip()
    platform = (parameters.get("platform") or "phone").strip().lower()
    call_type = (parameters.get("call_type") or "voice").strip().lower()

    if not target:
        return "Sir, please specify who you would like to call."

    if "whatsapp" in platform or "wp" in platform or "wapp" in platform:
        return make_whatsapp_call(target, call_type=call_type, player=player)
    else:
        return make_phone_call(target, player=player)


TOOL = {
    "name": "phone_call",
    "description": (
        "THE tool for placing outbound voice and video phone calls. "
        "Supports regular cellular phone calls via Phone Link/tel: (DEFAULT) and WhatsApp Desktop calls. "
        "Automatically looks up contact names in Google Contacts to resolve their phone numbers. "
        "Use platform='phone' for regular calls (e.g. 'call Arnab', 'call +91...'). "
        "Use platform='whatsapp' when the user explicitly specifies WhatsApp (e.g. 'call Rahul on WhatsApp', 'WhatsApp call Amit')."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "target": {
                "type": "STRING",
                "description": "Name of the contact to look up in Google Contacts, or direct phone number with country code (e.g. 'Arnab', 'Rahul', '+919876543210')."
            },
            "platform": {
                "type": "STRING",
                "enum": ["phone", "whatsapp"],
                "description": "The calling platform. Default is 'phone' (regular cellular call). Set to 'whatsapp' if user explicitly requests WhatsApp."
            },
            "call_type": {
                "type": "STRING",
                "enum": ["voice", "video"],
                "description": "Type of call. Default is 'voice'. Set to 'video' if video call requested."
            }
        },
        "required": ["target"]
    },
    "handler": phone_call_action,
}
