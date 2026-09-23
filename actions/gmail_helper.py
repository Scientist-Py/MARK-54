"""
actions/gmail_helper.py — Headless Gmail Integration for JARVIS
Fetches unread emails, reads email body, searches messages, launches the React-based Gmail Composer UI,
and sends/replies to emails in the background.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
import webbrowser
from email.mime.text import MIMEText
from pathlib import Path
import sys

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))

from core.google_auth import get_google_credentials
from core import confirm as confirm_gate

DRAFT_FILE = BASE_DIR / "config" / "active_draft.json"


def _get_gmail_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Gmail] ❌ Service build error: {e}")
        return None


def _extract_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    body_data = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain" and "data" in part.get("body", {}):
                body_data = part["body"]["data"]
                break
            elif "parts" in part:
                sub = _extract_body(part)
                if sub:
                    return sub
        if not body_data:
            for part in payload["parts"]:
                if part.get("mimeType", "") == "text/html" and "data" in part.get("body", {}):
                    body_data = part["body"]["data"]
                    break
    elif "data" in payload.get("body", {}):
        body_data = payload["body"]["data"]

    if body_data:
        try:
            decoded = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", decoded)
            text = re.sub(r"\s+", " ", text).strip()
            return text
        except Exception:
            return ""
    return ""


def _get_unread_emails(service, max_results: int = 5) -> str:
    try:
        results = service.users().messages().list(
            userId="me",
            q="is:unread label:INBOX",
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return "Sir, your inbox is clean. You have no unread emails."

        lines = []
        for msg in messages:
            msg_data = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            
            subject = headers.get("subject", "(No Subject)")
            sender  = headers.get("from", "Unknown Sender")
            snippet = msg_data.get("snippet", "")

            if "<" in sender:
                sender = sender.split("<")[0].strip().replace('"', '')

            lines.append(f"• From: {sender} | Subject: {subject}\n  Preview: \"{snippet[:100]}...\" (ID: {msg['id']})")

        count = len(messages)
        email_word = "email" if count == 1 else "emails"
        return f"Sir, you have {count} recent unread {email_word}:\n\n" + "\n\n".join(lines)

    except Exception as e:
        return f"Could not fetch unread emails: {e}"


def _read_email(service, query: str = "", message_id: str = "") -> str:
    """Read the full body content of an email matching query or message_id."""
    try:
        target_id = message_id.strip()
        if not target_id:
            if not query:
                return "Sir, please specify which email you would like me to read."
            results = service.users().messages().list(userId="me", q=query, maxResults=1).execute()
            messages = results.get("messages", [])
            if not messages:
                return f"Sir, no email found matching '{query}'."
            target_id = messages[0]["id"]

        msg = service.users().messages().get(userId="me", id=target_id, format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "(No Subject)")
        sender = headers.get("from", "Unknown")
        date_str = headers.get("date", "")
        body_text = _extract_body(msg.get("payload", {})) or msg.get("snippet", "")

        return (
            f"Sir, here are the details for the email:\n"
            f"• From: {sender}\n"
            f"• Date: {date_str}\n"
            f"• Subject: {subject}\n\n"
            f"Content:\n{body_text[:1200]}"
        )
    except Exception as e:
        return f"Failed to read email: {e}"


def _search_emails(service, query: str, max_results: int = 5) -> str:
    if not query:
        return "Please specify what you would like me to search for in your emails, sir."
    try:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"No emails found matching '{query}', sir."

        lines = []
        for msg in messages:
            msg_data = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            
            subject = headers.get("subject", "(No Subject)")
            sender  = headers.get("from", "Unknown")
            snippet = msg_data.get("snippet", "")

            if "<" in sender:
                sender = sender.split("<")[0].strip().replace('"', '')

            lines.append(f"• From: {sender} | Subject: {subject}\n  Summary: {snippet[:120]}... (ID: {msg['id']})")

        return f"Found {len(messages)} emails matching '{query}':\n\n" + "\n\n".join(lines)

    except Exception as e:
        return f"Email search failed: {e}"


def _send_email_direct(service, to: str, subject: str, body: str) -> str:
    try:
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject or "Message from JARVIS"

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
        return f"Email successfully sent to {to} with subject '{subject or 'Message from JARVIS'}', sir."
    except Exception as e:
        return f"Failed to send email: {e}"


def _open_react_composer(draft_data: dict) -> None:
    """Open the React Gmail Composer UI in browser with the pre-filled draft."""
    try:
        DRAFT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DRAFT_FILE.write_text(json.dumps(draft_data, indent=2), encoding="utf-8")
        
        # Build URL with query params
        params = urllib.parse.urlencode({
            "to": draft_data.get("to", ""),
            "subject": draft_data.get("subject", ""),
            "body": draft_data.get("body", ""),
            "type": draft_data.get("type", "email"),
            "title": draft_data.get("title", ""),
            "content": draft_data.get("content", ""),
            "category": draft_data.get("category", "email"),
        })
        url = f"http://localhost:8000/compose?{params}"
        print(f"[GmailComposer] 🌐 Opening React Composer UI: {url}")
        webbrowser.open(url)
    except Exception as e:
        print(f"[GmailComposer] ⚠️ Failed to launch browser: {e}")


def _send_email(service, to: str, subject: str, body: str, confirmed: bool = False, player=None) -> str:
    if not to or not body:
        return "Sir, both a recipient email address and message body are required to send an email."

    email_subject = subject or "Message from JARVIS"

    def _do_send():
        return _send_email_direct(service, to, email_subject, body)

    def _do_regen():
        try:
            from core import gemini
            prompt = f"Rephrase and polish this professional email to {to} on subject '{email_subject}':\n\n{body}\n\nReturn ONLY the improved email body text."
            resp = gemini.call(prompt)
            if resp and resp.text:
                return f"To: {to}\nSubject: {email_subject}\n\n" + resp.text.strip()
        except Exception as e:
            print(f"[GmailHelper] ⚠️ Regenerate failed: {e}")
        return f"To: {to}\nSubject: {email_subject}\n\n{body}"

    if player and hasattr(player, "show_studio"):
        try:
            player.show_studio(
                f"EMAIL: {email_subject}",
                f"To: {to}\nSubject: {email_subject}\n\n{body}",
                "email",
                confirm_cb=_do_send,
                regen_cb=_do_regen
            )
        except Exception as e:
            print(f"[GmailHelper] ⚠️ Failed to show Studio: {e}")
    elif player and hasattr(player, "show_content"):
        try:
            player.show_content(f"EMAIL DRAFT: {email_subject}", f"To: {to}\nSubject: {email_subject}\n\n{body}")
        except Exception:
            pass

    return f"Sir, I have prepared the email draft to {to} in your JARVIS Studio window. You can review, edit, regenerate, or click 'Confirm & Send Email' directly in the Studio window."


def _send_reply_direct(service, recipient: str, reply_subject: str, body: str, target_thread_id: str = "", orig_msg_id: str = "") -> str:
    try:
        message = MIMEText(body)
        message["to"] = recipient
        message["subject"] = reply_subject
        if orig_msg_id:
            message["In-Reply-To"] = orig_msg_id
            message["References"] = orig_msg_id

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        payload = {"raw": raw_message}
        if target_thread_id:
            payload["threadId"] = target_thread_id

        service.users().messages().send(userId="me", body=payload).execute()
        return f"Sir, reply successfully sent to {recipient} on subject '{reply_subject}'."
    except Exception as e:
        return f"Failed to send reply: {e}"


def _reply_to_email(
    service,
    to: str = "",
    subject: str = "",
    body: str = "",
    query: str = "",
    message_id: str = "",
    thread_id: str = "",
    confirmed: bool = False,
    player=None,
) -> str:
    """Reply to an existing email message/thread with React Composer and confirmation."""
    if not body:
        return "Sir, please specify what message body you would like to reply with."

    try:
        if not message_id:
            search_q = query or (f"from:{to}" if to else "") or "is:unread label:INBOX"
            results = service.users().messages().list(userId="me", q=search_q, maxResults=1).execute()
            messages = results.get("messages", [])
            if not messages:
                return f"Sir, could not locate an email thread matching '{search_q}' to reply to."
            message_id = messages[0]["id"]

        orig_msg = service.users().messages().get(userId="me", id=message_id, format="metadata").execute()
        headers = {h["name"].lower(): h["value"] for h in orig_msg.get("payload", {}).get("headers", [])}

        target_thread_id = thread_id or orig_msg.get("threadId", "")
        orig_from = headers.get("from", "")
        orig_subject = headers.get("subject", "No Subject")
        orig_msg_id = headers.get("message-id", "")

        reply_to_addr = headers.get("reply-to", orig_from)
        if "<" in reply_to_addr and ">" in reply_to_addr:
            match = re.search(r"<([^>]+)>", reply_to_addr)
            if match:
                reply_to_addr = match.group(1)

        recipient = to or reply_to_addr
        if not recipient:
            return "Sir, could not determine recipient address from the original email."

        reply_subject = subject or orig_subject
        if not reply_subject.lower().startswith("re:"):
            reply_subject = f"Re: {reply_subject}"

        draft_data = {
            "type": "email",
            "to": recipient,
            "subject": reply_subject,
            "body": body,
        }

        # 1. Open React Gmail Composer in browser
        _open_react_composer(draft_data)

        # 2. Show on HUD Content Panel
        if player and hasattr(player, "show_content"):
            try:
                player.show_content(f"REPLY DRAFT: {reply_subject}", f"To: {recipient}\nSubject: {reply_subject}\n\n{body}")
            except Exception:
                pass

        if not confirmed:
            def _execute():
                return _send_reply_direct(service, recipient, reply_subject, body, target_thread_id, orig_msg_id)

            return confirm_gate.request(
                key=f"reply_email_{recipient}",
                title=f"Reply to {recipient}",
                detail=f"Subject: {reply_subject}\n\n{body[:250]}...",
                run=_execute,
            )

        return _send_reply_direct(service, recipient, reply_subject, body, target_thread_id, orig_msg_id)

    except Exception as e:
        return f"Failed to prepare email reply: {e}"


def gmail_action(
    parameters: dict,
    player=None,
    session_memory=None,
    **kwargs
) -> str:
    action      = parameters.get("action", "get_unread").lower().strip()
    query       = parameters.get("query", "")
    to          = parameters.get("to", "")
    subject     = parameters.get("subject", "")
    body        = parameters.get("body", "")
    message_id  = parameters.get("message_id", "")
    thread_id   = parameters.get("thread_id", "")
    confirmed   = bool(parameters.get("confirmed", False))
    max_results = parameters.get("max_results", 5)

    service = _get_gmail_service()
    if not service:
        msg = "Sir, Gmail is not authenticated. Please check your credentials."
        _log(msg, player)
        return msg

    if action in ("get_unread", "unread", "inbox", "check"):
        result = _get_unread_emails(service, max_results)
    elif action in ("read_email", "read", "view"):
        result = _read_email(service, query=query, message_id=message_id)
    elif action in ("search_emails", "search", "find"):
        result = _search_emails(service, query, max_results)
    elif action in ("reply_to_email", "reply", "respond"):
        result = _reply_to_email(
            service,
            to=to,
            subject=subject,
            body=body,
            query=query,
            message_id=message_id,
            thread_id=thread_id,
            confirmed=confirmed,
            player=player,
        )
    elif action in ("send_email", "send", "compose"):
        result = _send_email(
            service,
            to=to,
            subject=subject,
            body=body,
            confirmed=confirmed,
            player=player,
        )
    else:
        result = _get_unread_emails(service, max_results)

    _log(result, player)

    if session_memory:
        try:
            session_memory.set_last_search(query="Gmail", response=result[:200])
        except Exception:
            pass

    return result


def _log(message: str, player=None) -> None:
    print(f"[Gmail] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "gmail_helper",
    "description": (
        "Reads unread emails, views email content, searches email history, drafts/sends new messages, "
        "and replies directly to email threads using the Gmail API. Opens the React Gmail Composer UI "
        "for instant user review and one-click sending."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["get_unread", "read_email", "search_emails", "send_email", "reply_to_email"],
                "description": "The email action: 'get_unread' to check inbox, 'read_email' to view full body, 'search_emails' to find messages, 'send_email' to compose/send, or 'reply_to_email' to reply to an email/thread."
            },
            "query": {
                "type": "STRING",
                "description": "For search_emails, read_email, or reply_to_email: keywords, sender name, or search query (e.g. 'from:NoBroker', 'interview scheduled')."
            },
            "to": {
                "type": "STRING",
                "description": "For send_email or reply_to_email: Recipient email address."
            },
            "subject": {
                "type": "STRING",
                "description": "For send_email or reply_to_email: Subject line."
            },
            "body": {
                "type": "STRING",
                "description": "For send_email or reply_to_email: The message body/reply text."
            },
            "message_id": {
                "type": "STRING",
                "description": "Optional specific Gmail message ID for read_email or reply_to_email."
            },
            "thread_id": {
                "type": "STRING",
                "description": "Optional specific Gmail thread ID for reply_to_email."
            },
            "confirmed": {
                "type": "BOOLEAN",
                "description": "Set to true only if the user has already explicitly confirmed sending this draft."
            },
            "max_results": {
                "type": "INTEGER",
                "description": "Maximum number of emails to retrieve (default 5)."
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": gmail_action,
}
