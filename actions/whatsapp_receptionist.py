"""
actions/whatsapp_receptionist.py — Live WhatsApp AI Call Receptionist for JARVIS
Detects incoming WhatsApp calls in real-time, answers calls cleanly, speaks Sir's custom reason
(in Hindi or English attributing Mr. Tushar Chauhan), immediately hangs up the call so the caller
cannot talk back, and displays real-time call status and summaries on the HUD.
"""

from __future__ import annotations

import os
import re
import sys
import time
import asyncio
import datetime
import threading
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE    = 0.02
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import winsdk.windows.ui.notifications.management as _mgmt
    import winsdk.windows.ui.notifications as _notif
    _WINSDK = True
except ImportError:
    _WINSDK = False

try:
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    _PYCAW = True
except ImportError:
    _PYCAW = False


# Global call state
_SEEN_NOTIFICATION_IDS = set()
_BASELINE_INITIALIZED = False
_CALL_STATE = {
    "is_active": False,
    "last_caller": "the caller",
    "last_announced_id": None,
    "last_announced_time": 0.0,
}


def is_call_in_progress() -> bool:
    return _CALL_STATE["is_active"]


def set_call_in_progress(val: bool):
    _CALL_STATE["is_active"] = val


def _is_whatsapp_audio_ringing() -> bool:
    """Check if WhatsApp is actively playing ringtone via Windows Core Audio."""
    if not _PYCAW:
        return False
    try:
        sessions = AudioUtilities.GetAllSessions()
        for s in sessions:
            p = s.Process
            if p and "whatsapp" in p.name().lower():
                if s.State == 1:
                    try:
                        meter = s._ctl.QueryInterface(IAudioMeterInformation)
                        if meter and meter.GetPeakValue() > 0.005:
                            return True
                    except Exception:
                        return True
    except Exception:
        pass
    return False


def _extract_caller_from_texts(texts: list[str]) -> str:
    """Extract clean caller name from notification text elements (e.g. 'Puneet')."""
    for t in texts:
        m = re.search(r"(?:incoming call from|incoming voice call from|incoming video call from|call from|from)\s+(.+)", t, re.IGNORECASE)
        if m:
            clean = m.group(1).strip()
            clean = re.sub(r"(?i)\s*-\s*whatsapp|\s*·\s*.*", "", clean).strip()
            if clean:
                return clean
        m2 = re.search(r"^(.+?)\s+(?:is calling|calling\.\.\.)", t, re.IGNORECASE)
        if m2:
            clean = m2.group(1).strip()
            if clean:
                return clean
    
    for t in texts:
        t_clean = t.strip()
        lower = t_clean.lower()
        if not any(k in lower for k in ["incoming", "voice call", "video call", "whatsapp", "truecaller", "identified by", "phone link", "calling"]):
            if len(t_clean) > 0:
                return t_clean

    return "the caller"


async def check_incoming_call_async() -> dict | None:
    """
    Check for LIVE incoming call notifications via WinSDK.
    Uses sequential notification ID comparison from the startup baseline.
    """
    global _BASELINE_INITIALIZED, _SEEN_NOTIFICATION_IDS

    if not _WINSDK:
        return None

    try:
        listener = _mgmt.UserNotificationListener.current
        await listener.request_access_async()
        notifications = await listener.get_notifications_async(_notif.NotificationKinds.TOAST)
        
        # Baseline initialization
        if not _BASELINE_INITIALIZED:
            for n in notifications:
                _SEEN_NOTIFICATION_IDS.add(n.id)
            _BASELINE_INITIALIZED = True
            return None

        # Check for newly arrived notifications
        for n in reversed(notifications):
            if n.id in _SEEN_NOTIFICATION_IDS:
                continue

            _SEEN_NOTIFICATION_IDS.add(n.id)

            try:
                app_name = n.app_info.display_info.display_name if n.app_info and n.app_info.display_info else ""
                app_id = n.app_info.app_user_model_id if n.app_info else ""
                
                texts = []
                if n.notification and n.notification.visual:
                    for b in n.notification.visual.bindings:
                        for el in b.get_text_elements():
                            texts.append(el.text.strip())
                
                full_text = " ".join(texts).lower()
                is_wa = "whatsapp" in app_name.lower() or "whatsapp" in app_id.lower()
                is_phone = "phone link" in app_name.lower() or "yourphone" in app_id.lower()
                
                if is_wa or is_phone:
                    call_keywords = [
                        "incoming call", "incoming voice call", "incoming video call",
                        "voice call", "video call", "call from", "calling...", "is calling"
                    ]
                    if any(k in full_text for k in call_keywords):
                        caller = _extract_caller_from_texts(texts)
                        _CALL_STATE["last_caller"] = caller
                        return {
                            "source": "WhatsApp" if is_wa else "Phone Link",
                            "id": str(n.id),
                            "caller": caller,
                            "texts": texts,
                        }
            except Exception:
                continue
    except Exception:
        pass

    # Secondary check: audio stream ringing
    now = time.time()
    if _is_whatsapp_audio_ringing():
        if (now - _CALL_STATE["last_announced_time"]) > 45.0:
            return {
                "source": "WhatsApp",
                "id": "audio_ringing",
                "caller": _CALL_STATE.get("last_caller") or "the caller",
                "texts": ["Active WhatsApp Audio Ringing"],
            }

    return None


import ctypes
from ctypes import wintypes

_AUTO_HANGUP_STATE = {
    "armed": False,
    "caller": "the caller",
    "reason": "",
    "source": "WhatsApp",
}

def is_auto_hangup_armed() -> bool:
    return _AUTO_HANGUP_STATE["armed"]

def set_auto_hangup_armed(val: bool, caller: str = "", reason: str = "", source: str = "WhatsApp"):
    _AUTO_HANGUP_STATE["armed"] = val
    _AUTO_HANGUP_STATE["caller"] = caller
    _AUTO_HANGUP_STATE["reason"] = reason
    _AUTO_HANGUP_STATE["source"] = source

def trigger_hangup_now(player=None) -> bool:
    """Invoked immediately after spoken message finishes playback to cut the call."""
    caller = _AUTO_HANGUP_STATE.get("caller") or "the caller"
    source = _AUTO_HANGUP_STATE.get("source") or "WhatsApp"
    _AUTO_HANGUP_STATE["armed"] = False
    set_call_in_progress(False)
    success = _trigger_decline_call(source=source)
    if player and hasattr(player, "write_log"):
        player.write_log(f"SYS: Call disconnected with {caller}.")
    print(f"[Receptionist] Call disconnected with {caller}.")
    return success


def _find_whatsapp_window_hwnd() -> int | None:
    """Find visible WhatsApp call or application window handle using Win32 API."""
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        matched = []
        def enum_cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                cls = cls_buf.value.lower()
                if ('whatsapp' in title or 'whatsapp' in cls or 'call' in title) and not ('taskbar' in title or 'shell' in title):
                    matched.append(hwnd)
            return True
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return matched[0] if matched else None
    except Exception:
        return None


def _clean_caller_name(caller: str) -> str:
    """Return clean personal caller name, or empty string if generic."""
    c = (caller or "").strip()
    c_lower = c.lower()
    if not c or any(k in c_lower for k in ["the caller", "whatsapp caller", "phone caller", "incoming call", "caller", "unknown", "someone", "undefined"]):
        return ""
    return c


def _convert_to_third_person(text: str) -> str:
    """Transform user's first-person response into clean third-person attribution for Sir."""
    t = (text or "").strip()
    if not t:
        return "He will contact you later."

    # Remove leading commands / prompt boilerplate
    t = re.sub(
        r"^(?:tell\s+(?:him|her|them|the\s+caller)|say\s+(?:that|to\s+(?:him|her|them))?|say|tell|inform\s+(?:him|her|them)?|that|and\s+say|answer\s+(?:it\s+)?and\s+say)\s*",
        "",
        t,
        flags=re.IGNORECASE
    ).strip()

    # Abbreviations
    t = re.sub(r"\bgf\b", "girlfriend", t, flags=re.IGNORECASE)
    t = re.sub(r"\bbf\b", "boyfriend", t, flags=re.IGNORECASE)

    # Pronoun replacements (1st person -> 3rd person)
    replacements = [
        (r"\b(?:i\s+am|i\'m|im)\s+busy\s+with\s+my\b", "He is busy with his"),
        (r"\b(?:i\s+am|i\'m|im)\s+with\s+my\b", "He is with his"),
        (r"\b(?:i\s+am|i\'m|im)\s+", "He is "),
        (r"\b(?:i\s+will|i\'ll|ill)\s+", "He will "),
        (r"\b(?:i\s+have|i\'ve|ive)\s+", "He has "),
        (r"\b(?:i\s+had)\s+", "He had "),
        (r"\b(?:i\s+cannot|i\s+can\'t|i\s+cant)\s+", "He cannot "),
        (r"\b(?:i\s+could\s+not|i\s+couldn\'t)\s+", "He could not "),
        (r"\b(?:i\s+was)\s+", "He was "),
        (r"\b(?:i\s+would|i\'d)\s+", "He would "),
        (r"\b(?:i\s+need\s+to)\s+", "He needs to "),
        (r"\b(?:i\s+want\s+to)\s+", "He wants to "),
        (r"\bmy\b", "his"),
        (r"\bmine\b", "his"),
        (r"\bme\b", "him"),
        (r"\bmyself\b", "himself"),
        (r"\bi\b", "He"),
    ]
    for p, r in replacements:
        t = re.sub(p, r, t, flags=re.IGNORECASE)

    t = re.sub(r"\s+", " ", t).strip()
    if not re.match(r"^(?:he\b|mr\b|tushar\b)", t, re.IGNORECASE):
        t = f"He is {t}" if any(t.lower().startswith(w) for w in ["busy", "driving", "sleeping", "working", "in ", "at ", "with "]) else f"He said {t}"

    if not t.endswith((".", "!", "?")):
        t += "."
    return t


def _clean_hindi_reason(text: str) -> str:
    """Transform Hindi first-person reason into respectful third-person."""
    t = (text or "").strip()
    if not t:
        return "baad me call karenge"
    t = re.sub(r"^(?:unko\s+bolo|unse\s+bolo|bol\s+do|bolna|unko\s+bolna|ki|unhe\s+bolo|kaho|bolo|say|tell)\s*", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\bgf\b", "girlfriend", t, flags=re.IGNORECASE)
    t = re.sub(r"\bbf\b", "boyfriend", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmain\s+(?:apni\s+)?", "wo apni ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmera\b", "unka", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmeri\b", "unki", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmere\b", "unke", t, flags=re.IGNORECASE)
    t = re.sub(r"\bmujhe\b", "unhe", t, flags=re.IGNORECASE)
    t = re.sub(r"\bkarta\s+hu\b|\bkarunga\b", "karenge", t, flags=re.IGNORECASE)
    t = re.sub(r"\bhu\b|\bhoon\b", "hain", t, flags=re.IGNORECASE)
    return t.strip()


def _win32_mouse_click(x: int, y: int):
    """Perform a hardware-level Win32 left click with realistic down-up hold."""
    try:
        user32 = ctypes.windll.user32
        MOUSEEVENTF_MOVE     = 0x0001
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP   = 0x0004
        MOUSEEVENTF_ABSOLUTE = 0x8000

        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.02)
        sw = user32.GetSystemMetrics(0) or 1920
        sh = user32.GetSystemMetrics(1) or 1080
        norm_x = int(x * 65535 / sw)
        norm_y = int(y * 65535 / sh)

        user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN, norm_x, norm_y, 0, 0)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP, norm_x, norm_y, 0, 0)
        time.sleep(0.02)
    except Exception:
        pass


def _trigger_answer_call(source: str = "WhatsApp") -> bool:
    """Answer the incoming WhatsApp call cleanly and bring call window into active connection."""
    try:
        if _PYAUTOGUI:
            pyautogui.FAILSAFE = False

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0) or 1920
        h = user32.GetSystemMetrics(1) or 1080

        VK_LWIN = 0x5B
        VK_SHIFT = 0x10
        VK_V = 0x56
        VK_RETURN = 0x0D
        VK_SPACE = 0x20
        VK_CONTROL = 0x11
        VK_A = 0x41

        def _burst():
            # 1. Dynamic check for floating WhatsApp Call Window
            try:
                import pygetwindow as gw
                for win in gw.getWindowsWithTitle("WhatsApp"):
                    if 200 < win.width < 900 and 200 < win.height < 900:
                        try:
                            win.activate()
                        except Exception:
                            pass
                        time.sleep(0.02)
                        # Click green answer button inside floating call window
                        _win32_mouse_click(win.left + int(win.width * 0.25), win.top + int(win.height * 0.88))
                        _win32_mouse_click(win.left + int(win.width * 0.35), win.top + int(win.height * 0.88))
                        _win32_mouse_click(win.left + int(win.width * 0.50), win.top + int(win.height * 0.88))
                        _win32_mouse_click(win.left + int(win.width * 0.15), win.top + int(win.height * 0.88))
            except Exception:
                pass

            # 2. Static targeting of floating Call Window (matches x:180-620, y:170-580 on 1080p)
            call_window_targets = [
                (240, 550),   # Green Answer button (left)
                (300, 550),   # Green Answer button (mid-left)
                (360, 550),   # Green Answer button (center)
                (400, 550),
                (300, 530),
                (400, 380),   # Call window body (focuses window)
            ]
            for cx, cy in call_window_targets:
                _win32_mouse_click(cx, cy)

            # 3. Focus Windows Notification Toast using Win + Shift + V
            user32.keybd_event(VK_LWIN, 0, 0, 0)
            user32.keybd_event(VK_SHIFT, 0, 0, 0)
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.03)
            user32.keybd_event(VK_V, 0, 2, 0)
            user32.keybd_event(VK_SHIFT, 0, 2, 0)
            user32.keybd_event(VK_LWIN, 0, 2, 0)
            time.sleep(0.04)

            # Send Enter & Space to activate primary action (Accept)
            user32.keybd_event(VK_RETURN, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(VK_RETURN, 0, 2, 0)
            time.sleep(0.02)
            user32.keybd_event(VK_SPACE, 0, 0, 0)
            time.sleep(0.02)
            user32.keybd_event(VK_SPACE, 0, 2, 0)

            # 4. Comprehensive hardware clicks across Windows 11 Toast notification area (bottom-right)
            toast_targets = [
                (w - 280, h - 90),   # Left Accept button on standard banner
                (w - 220, h - 90),   # Mid-left button
                (w - 180, h - 90),   # Center-right button
                (w - 90,  h - 140),  # Right-side circular green button
                (w - 90,  h - 90),   # Right-bottom button
                (w - 200, h - 140),  # Toast body (activates call window)
                (w - 180, h - 110),
                (w - 240, h - 110),
            ]
            for tx, ty in toast_targets:
                _win32_mouse_click(tx, ty)

            # 5. WhatsApp in-app answer shortcut
            hwnd = _find_whatsapp_window_hwnd()
            if hwnd:
                try:
                    user32.SetForegroundWindow(hwnd)
                    user32.ShowWindow(hwnd, 9)
                    time.sleep(0.02)
                    user32.keybd_event(VK_CONTROL, 0, 0, 0)
                    user32.keybd_event(VK_SHIFT, 0, 0, 0)
                    user32.keybd_event(VK_A, 0, 0, 0)
                    time.sleep(0.02)
                    user32.keybd_event(VK_A, 0, 2, 0)
                    user32.keybd_event(VK_SHIFT, 0, 2, 0)
                    user32.keybd_event(VK_CONTROL, 0, 2, 0)
                except Exception:
                    pass

        # Execute Burst 1 immediately
        _burst()
        # Execute Burst 2 after 150ms to ensure complete connection
        time.sleep(0.15)
        _burst()

        return True
    except Exception as e:
        print(f"[Receptionist] Answer error: {e}")
        return False


def _trigger_decline_call(source: str = "WhatsApp") -> bool:
    """Disconnect and hang up the active WhatsApp call cleanly."""
    try:
        if _PYAUTOGUI:
            pyautogui.FAILSAFE = False

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        w = user32.GetSystemMetrics(0) or 1920
        h = user32.GetSystemMetrics(1) or 1080

        # 1. Dynamic check for floating Call Window hangup button
        try:
            import pygetwindow as gw
            for win in gw.getWindowsWithTitle("WhatsApp"):
                if 200 < win.width < 900 and 200 < win.height < 900:
                    try:
                        win.activate()
                    except Exception:
                        pass
                    time.sleep(0.02)
                    # Click red decline button in floating window
                    _win32_mouse_click(win.left + int(win.width * 0.88), win.top + int(win.height * 0.88))
                    _win32_mouse_click(win.left + int(win.width * 0.80), win.top + int(win.height * 0.88))
        except Exception:
            pass

        # 2. Static Red Decline button coordinates on Call Window & Toast
        decline_targets = [
            (580, 550),          # Red Decline button on floating call window
            (560, 550),
            (int(w * 0.15), int(h * 0.55)),
            (int(w * 0.5),  int(h * 0.55)),
            (w - 100, h - 90),
            (w - 100, h - 100),
            (w - 140, h - 90),
        ]
        for dx, dy in decline_targets:
            _win32_mouse_click(dx, dy)

        # 3. Focus WhatsApp call window
        hwnd = _find_whatsapp_window_hwnd()
        if hwnd:
            try:
                user32.SetForegroundWindow(hwnd)
                user32.ShowWindow(hwnd, 9)
                time.sleep(0.03)
            except Exception:
                pass

        # 4. Send WhatsApp decline & hangup shortcuts
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        VK_D = 0x44
        VK_H = 0x48
        VK_ESCAPE = 0x1B

        # Ctrl + Shift + D
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_D, 0, 2, 0)
        user32.keybd_event(VK_SHIFT, 0, 2, 0)
        user32.keybd_event(VK_CONTROL, 0, 2, 0)
        time.sleep(0.02)

        # Ctrl + Shift + H
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(VK_H, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_H, 0, 2, 0)
        user32.keybd_event(VK_SHIFT, 0, 2, 0)
        user32.keybd_event(VK_CONTROL, 0, 2, 0)
        time.sleep(0.02)

        # Esc
        user32.keybd_event(VK_ESCAPE, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(VK_ESCAPE, 0, 2, 0)

        return True
    except Exception as e:
        print(f"[Receptionist] Decline error: {e}")
        return False


def _schedule_auto_hangup(delay_seconds: float = 7.0, source: str = "WhatsApp", player=None, caller: str = "caller"):
    """Fallback timer to ensure call is disconnected if main loop event misses."""
    def _hangup_worker():
        time.sleep(delay_seconds)
        if is_auto_hangup_armed():
            try:
                trigger_hangup_now(player=player)
            except Exception as e:
                print(f"[Receptionist] Fallback hangup error: {e}")
    t = threading.Thread(target=_hangup_worker, daemon=True)
    t.start()


def whatsapp_receptionist_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action        = (parameters.get("action") or "deliver_message_and_hangup").lower().strip()
    caller_hint   = (parameters.get("caller") or "").strip()
    reason_input  = (parameters.get("reason") or "").strip()
    custom_msg    = (parameters.get("message") or "").strip()

    raw_reason_clean = (reason_input or custom_msg or "").strip()
    caller_name = caller_hint or _CALL_STATE.get("last_caller") or "the caller"
    source = "WhatsApp"

    # 1. Check incoming status
    if action in ("check_incoming", "status", "who_is_calling"):
        real_caller = _clean_caller_name(caller_name)
        return f"Sir, the incoming WhatsApp call is from {real_caller or 'an incoming caller'}."

    # 2. Answer call, speak custom reason on Sir's behalf, and immediately hang up
    elif action in ("deliver_message_and_hangup", "deliver_and_cut", "tell_and_cut", "busy_message", "say_and_hangup"):
        set_call_in_progress(True)
        _trigger_answer_call(source=source)

        lower_r = raw_reason_clean.lower()
        # Detect Hindi vs English
        is_hindi = any(
            w in lower_r for w in [
                "bolo", "bol do", "bolna", "baad me", "karta hu", "karunga", "karungi", "hoon",
                "vyast", "abhi", "unko", "unse", "thoda", "karo", "batana", "hai", "hain", "main", "baad"
            ]
        )

        real_name = _clean_caller_name(caller_name)
        greeting_en = f"Hello {real_name}," if real_name else "Hello,"
        greeting_hi = f"Namaste {real_name}," if real_name else "Namaste,"

        if is_hindi:
            cleaned_hindi_reason = _clean_hindi_reason(raw_reason_clean)
            spoken_message = (
                f"{greeting_hi} Mr. Tushar Chauhan abhi vyast hain. "
                f"Unhone kaha hai ki {cleaned_hindi_reason}. Dhanyawad."
            )
        else:
            reason_phrase = _convert_to_third_person(raw_reason_clean)
            spoken_message = (
                f"{greeting_en} Mr. Tushar Chauhan is busy right now. "
                f"{reason_phrase} Thank you."
            )

        # Arm immediate auto-hangup when audio playback ends
        set_auto_hangup_armed(True, caller=caller_name, reason=spoken_message, source=source)
        # Also arm safety timeout (12s) in case playback event doesn't fire
        _schedule_auto_hangup(delay_seconds=12.0, source=source, player=player, caller=caller_name)

        display_name = real_name or "CALLER"
        if player and hasattr(player, "show_content"):
            try:
                card_text = (
                    f"Caller: {display_name}\n"
                    f"Status: Message Delivering & Auto-Disconnecting\n\n"
                    f"Spoken into Call:\n'{spoken_message}'\n\n"
                    f"Call will be hung up immediately after message."
                )
                player.show_content(f"DELIVERING MESSAGE: {display_name.upper()}", card_text)
            except Exception:
                pass

        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Answering call to inform {display_name}.")
            except Exception:
                pass

        # Instruct Gemini to speak ONLY the exact message into the call
        return (
            f"[CALL_MESSAGE_DELIVERED] Call is connected with {display_name}. "
            f"Speak ONLY this exact message into the call now: '{spoken_message}'"
        )

    # 3. Answer as AI Receptionist (JARVIS speaks to caller and takes a message)
    elif action in ("answer_as_receptionist", "receptionist", "talk_to_him", "take_message"):
        set_call_in_progress(True)
        _trigger_answer_call(source=source)

        greeting = (
            f"Hello, you have reached JARVIS, personal AI assistant. "
            f"Sir is currently away from his desk. "
            f"I am attending this call on his behalf. How may I assist you, or what message should I pass to him?"
        )

        if player and hasattr(player, "show_content"):
            try:
                card_text = (
                    f"Status: AI Receptionist Answering\n"
                    f"Caller: {caller_name}\n\n"
                    f"JARVIS Greeting Spoken:\n'{greeting}'\n\n"
                    f"Listening for caller's message..."
                )
                player.show_content(f"WHATSAPP CALL ACTIVE: {caller_name.upper()}", card_text)
            except Exception:
                pass

        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Answering {source} call from {caller_name} as AI Receptionist.")
            except Exception:
                pass

        return (
            f"[RECEPTIONIST_CALL_ACTIVE] Call answered with {caller_name}. "
            f"Immediately speak this exact greeting directly to the caller in your natural voice: '{greeting}' "
            f"Then listen to what they say, take their message politely, and summarize it for Sir."
        )

    # 4. Answer for user directly (Tushar speaks to caller)
    elif action in ("answer_call", "answer", "accept", "pick_up"):
        set_call_in_progress(True)
        _trigger_answer_call(source=source)
        if player and hasattr(player, "show_content"):
            try:
                player.show_content(
                    f"WHATSAPP CALL CONNECTED: {caller_name.upper()}",
                    f"Caller: {caller_name}\nStatus: Call Connected\nMicrophone: Active"
                )
            except Exception:
                pass
        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Answered WhatsApp call from {caller_name}.")
            except Exception:
                pass
        return f"Sir, I have answered the WhatsApp call from {caller_name}. You are connected."

    # 5. Decline call
    elif action in ("decline_call", "decline", "reject", "cut"):
        set_call_in_progress(False)
        _trigger_decline_call(source=source)
        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Declined call from {caller_name}.")
            except Exception:
                pass
        return f"Sir, I have declined the call from {caller_name}."

    # 6. End call and save note
    elif action in ("end_call", "hang_up", "save_note"):
        set_call_in_progress(False)
        _trigger_decline_call(source=source)

        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        call_note = (
            f"Caller: {caller_name}\n"
            f"Time: {ts}\n\n"
            f"Message Summary:\n{custom_msg or '(Call completed)'}"
        )

        if player and hasattr(player, "show_content"):
            try:
                player.show_content(f"CALL SUMMARY: {caller_name.upper()}", call_note)
            except Exception:
                pass

        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"SYS: Call ended with {caller_name}. Summary saved on HUD.")
            except Exception:
                pass

        return f"Sir, the call with {caller_name} has ended. I have displayed their message summary on your HUD."

    return f"Sir, I have processed the call action for {caller_name}."


TOOL = {
    "name": "whatsapp_receptionist",
    "description": (
        "Controls incoming WhatsApp calls: automatically answers the call, delivers Sir's busy message on Mr. Tushar Chauhan's behalf "
        "(in Hindi or English, e.g. 'Mr. Tushar Chauhan is busy right now, he will contact you later' / 'Mr. Tushar Chauhan abhi vyast hain, baad me call karenge'), "
        "and immediately cuts/hangs up the call so the caller cannot talk back; or declines the call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": [
                    "deliver_message_and_hangup",
                    "answer_call",
                    "decline_call",
                    "check_incoming",
                    "end_call"
                ],
                "description": (
                    "Action to perform: 'deliver_message_and_hangup' (default) to answer, speak Sir's busy reason to the caller and immediately cut the call; "
                    "'decline_call' to reject the call; 'answer_call' to connect call for Sir; or 'check_incoming' to see who is calling."
                )
            },
            "caller": {
                "type": "STRING",
                "description": "Caller name if known or extracted (e.g. 'Puneet')."
            },
            "reason": {
                "type": "STRING",
                "description": "Reason or message given by Sir in English or Hindi (e.g. 'I will contact him later, I am busy right now', 'baad me call karta hu, abhi thoda busy hu')."
            },
            "message": {
                "type": "STRING",
                "description": "Summary or note of what the caller said to display on HUD when ending the call."
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": whatsapp_receptionist_action,
}
