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
EMAIL_MEMORY_FILE = BASE_DIR / "memory" / "email_contacts.json"


def _load_email_memory() -> dict[str, str]:
    try:
        if EMAIL_MEMORY_FILE.exists():
            return json.loads(EMAIL_MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[GmailMemory] ⚠️ Load failed: {e}")
    return {}


def _save_email_memory(data: dict[str, str]):
    try:
        EMAIL_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        EMAIL_MEMORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[GmailMemory] ⚠️ Save failed: {e}")


def _remember_email_contact(name_or_key: str, email: str):
    if not name_or_key or not email or "@" not in email:
        return
    mem = _load_email_memory()
    key = name_or_key.strip().lower()
    mem[key] = email.strip()

    # Also save prefix key from email address if applicable
    email_user = email.split("@")[0].replace(".", " ").replace("_", " ").replace("-", " ").strip().lower()
    if email_user and email_user not in mem:
        mem[email_user] = email.strip()

    _save_email_memory(mem)


PENDING_CHOICES_FILE = BASE_DIR / "memory" / "pending_contact_choices.json"


def _load_pending_choices() -> list[dict]:
    try:
        if PENDING_CHOICES_FILE.exists():
            return json.loads(PENDING_CHOICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_pending_choices(choices: list[dict]):
    try:
        PENDING_CHOICES_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_CHOICES_FILE.write_text(json.dumps(choices, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[GmailMemory] ⚠️ Save pending choices failed: {e}")


def _clear_pending_choices():
    try:
        if PENDING_CHOICES_FILE.exists():
            PENDING_CHOICES_FILE.unlink()
    except Exception:
        pass


def _resolve_numeric_choice(to_input: str) -> dict | None:
    raw = to_input.strip().lower()
    choices = _load_pending_choices()
    if not choices:
        return None

    idx = None
    if raw.isdigit():
        val = int(raw)
        if 1 <= val <= len(choices):
            idx = val - 1
    else:
        num_map = {
            "first": 0, "1st": 0, "one": 0, "option 1": 0, "number 1": 0,
            "second": 1, "2nd": 1, "two": 1, "option 2": 1, "number 2": 1,
            "third": 2, "3rd": 2, "three": 2, "option 3": 2, "number 3": 2,
            "fourth": 3, "4th": 3, "four": 3, "option 4": 3, "number 4": 3,
            "fifth": 4, "5th": 4, "five": 4, "option 5": 4, "number 5": 4,
        }
        for k, v in num_map.items():
            if k in raw and v < len(choices):
                idx = v
                break

    if idx is not None and 0 <= idx < len(choices):
        selected = choices[idx]
        _clear_pending_choices()
        return selected
    return None


def _resolve_recipient(to_input: str) -> tuple[str, str]:
    """
    Resolves recipient name or input to an email address.
    1. Direct email address -> remembers and returns it.
    2. Check numeric choice selection (1, 2, 3...) from pending choices.
    3. Persistent memory (memory/email_contacts.json).
    4. Google Contacts search:
       - 1 contact with email -> returns email directly.
       - 2+ contacts with email -> shows numbered list (1, 2, 3) and asks user.
       - Contact found without email -> returns clear warning.
    """
    raw = (to_input or "").strip()
    if not raw:
        return "", "Sir, please specify a recipient name or email address."

    # Direct email address provided
    if "@" in raw:
        prefix = raw.split("@")[0].replace(".", " ").replace("_", " ").strip()
        _remember_email_contact(prefix, raw)
        return raw, ""

    # Check pending numeric choice selection (e.g. user answered "1" or "option 2")
    num_choice = _resolve_numeric_choice(raw)
    if num_choice:
        c_name = num_choice.get("name", raw)
        c_email = num_choice.get("email", "")
        if c_email:
            _remember_email_contact(c_name, c_email)
            _remember_email_contact(raw, c_email)
            print(f"[Gmail] 🎯 Resolved selection option '{raw}' -> {c_name} ({c_email})")
            return c_email, ""

    key = raw.lower()
    mem = _load_email_memory()

    # Match in persistent memory
    for k, v in mem.items():
        if key == k or key in k or k in key:
            print(f"[GmailMemory] 🎯 Resolved '{raw}' from persistent memory -> {v}")
            return v, ""

    # Search Google Contacts
    try:
        from actions.google_contacts import search_contacts
        contacts = search_contacts(raw, max_results=10)
        contacts_with_emails = []

        if contacts:
            for c in contacts:
                c_name = c.get("name") or "Contact"
                emails = c.get("emails", [])
                for em in emails:
                    if em and "@" in em and {"name": c_name, "email": em} not in contacts_with_emails:
                        contacts_with_emails.append({"name": c_name, "email": em})

            # CASE 1: Exactly 1 contact found with email
            if len(contacts_with_emails) == 1:
                item = contacts_with_emails[0]
                _remember_email_contact(raw, item["email"])
                _remember_email_contact(item["name"], item["email"])
                print(f"[Gmail] 🎯 Resolved '{raw}' from Google Contacts -> {item['email']}")
                return item["email"], ""

            # CASE 2: Multiple matching contacts found with email -> Disambiguate with numbered list!
            elif len(contacts_with_emails) > 1:
                _save_pending_choices(contacts_with_emails)
                lines = []
                for idx, c in enumerate(contacts_with_emails, 1):
                    lines.append(f"{idx}. {c['name']} ({c['email']})")

                prompt_msg = (
                    f"Sir, I found multiple contacts matching '{raw}':\n"
                    + "\n".join(lines)
                    + "\n\nWhich one would you like to send to, Sir? (Please specify 1, 2, or 3)"
                )
                return "", prompt_msg

            # CASE 3: Contacts found but none have an email listed
            else:
                found_name = contacts[0].get("name") or raw
                return "", f"Sir, the contact '{found_name}' does not have an email address."
    except Exception as e:
        print(f"[Gmail] ⚠️ Google Contacts search error: {e}")

    # No email address found anywhere
    return "", f"Sir, I could not find an email address for '{raw}'."


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


def _enrich_email_content(to: str, subject: str, body: str, search_topic: str = "", player=None) -> tuple[str, str]:
    """Research topic via web search and generate a long, comprehensive, professional email."""
    topic_query = (search_topic or subject or "").strip()
    search_data = ""

    if search_topic or (topic_query and len((body or "").strip().split()) < 25):
        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"[Gmail] 🔍 Researching topic on web: '{topic_query}'...")
            except Exception:
                pass
        try:
            from actions.web_search import web_search
            search_res = web_search({"query": topic_query, "mode": "search"}, player=player)
            if search_res:
                search_data = str(search_res)[:3500]
        except Exception as se:
            print(f"[Gmail] ⚠️ Topic web search error: {se}")

    try:
        from core import gemini
        prompt = f"""You are an executive assistant for JARVIS crafting a comprehensive, detailed, long-form professional email.

Recipient: {to}
Subject Idea: {subject or search_topic or 'Update'}
Given Content / Notes: {body}

Web Research Findings:
{search_data if search_data else 'None'}

Instructions:
1. Formulate a crisp, professional Subject Line if none was provided.
2. Write a thorough, comprehensive, long-form email body (3 to 6 substantial paragraphs, with bullet points or key takeaways if applicable).
3. Integrate real facts, latest news, and key details from the Web Research Findings into the email body.
4. Use professional formatting, clear greetings, smooth paragraph transitions, and a formal closing signature.
5. Return ONLY valid JSON with keys "subject" and "body".
"""
        resp = gemini.call(prompt, tier=gemini.SMART, timeout_ms=35000)
        if resp and resp.text:
            text = resp.text.strip()
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text).strip()
            data = json.loads(text)
            final_sub = data.get("subject") or subject or f"Update: {topic_query}"
            final_body = data.get("body") or body
            return final_sub, final_body
    except Exception as e:
        print(f"[Gmail] ⚠️ Email enrichment error: {e}")

    return subject or f"Message regarding {search_topic or 'Update'}", body or "Please see attached update."


def _send_email(service, to: str, subject: str, body: str, search_topic: str = "", player=None) -> str:
    if not to:
        return "Sir, please specify a recipient name or email address."

    resolved_to, err_msg = _resolve_recipient(to)
    if err_msg:
        return err_msg

    # Perform topic research & long email synthesis
    email_subject, email_body = _enrich_email_content(resolved_to, subject, body, search_topic=search_topic, player=player)

    # 1. Show sent email in JARVIS Studio Window
    if player and hasattr(player, "show_studio"):
        try:
            player.show_studio(f"SENT EMAIL: {email_subject}", f"To: {resolved_to}\nSubject: {email_subject}\n\n{email_body}", "email")
        except Exception:
            pass
    elif player and hasattr(player, "show_content"):
        try:
            player.show_content(f"SENT EMAIL: {email_subject}", f"To: {resolved_to}\nSubject: {email_subject}\n\n{email_body}")
        except Exception:
            pass

    # 2. Send DIRECTLY without asking for confirmation
    return _send_email_direct(service, resolved_to, email_subject, email_body)


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
        return f"Sir, reply successfully sent directly to {recipient} on subject '{reply_subject}'."
    except Exception as e:
        return f"Failed to send reply: {e}"


def _reply_to_email(
    service,
    to: str = "",
    subject: str = "",
    body: str = "",
    search_topic: str = "",
    query: str = "",
    message_id: str = "",
    thread_id: str = "",
    player=None,
) -> str:
    """Reply to an existing email message/thread directly."""
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

        recipient = reply_to_addr
        if to:
            res_rec, err_m = _resolve_recipient(to)
            if err_m:
                return err_m
            if res_rec:
                recipient = res_rec

        if not recipient:
            return "Sir, could not determine recipient address for the email reply."

        reply_subject = subject or orig_subject
        if not reply_subject.lower().startswith("re:"):
            reply_subject = f"Re: {reply_subject}"

        # Perform enrichment if topic specified or short body
        if search_topic or (body and len(body.strip().split()) < 25):
            reply_subject, body = _enrich_email_content(recipient, reply_subject, body, search_topic=search_topic, player=player)

        # Show in JARVIS Studio Window
        if player and hasattr(player, "show_studio"):
            try:
                player.show_studio(f"SENT REPLY: {reply_subject}", f"To: {recipient}\nSubject: {reply_subject}\n\n{body}", "email")
            except Exception:
                pass

        # Send reply DIRECTLY without confirmation
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
    search_topic = parameters.get("search_topic", "")
    message_id  = parameters.get("message_id", "")
    thread_id   = parameters.get("thread_id", "")
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
            search_topic=search_topic,
            query=query,
            message_id=message_id,
            thread_id=thread_id,
            player=player,
        )
    elif action in ("send_email", "send", "compose"):
        result = _send_email(
            service,
            to=to,
            subject=subject,
            body=body,
            search_topic=search_topic,
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
        "Reads unread emails, views email content, searches email history, composes/sends new emails directly, "
        "and replies to email threads using the Gmail API. Supports automatic web research for topic-based emails "
        "(e.g. Elon Musk projects, AI news) to generate comprehensive long-form emails and send them directly."
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
                "description": "For send_email or reply_to_email: Message body text."
            },
            "search_topic": {
                "type": "STRING",
                "description": "Optional topic to research on the web before sending (e.g., 'Elon Musk new project', 'latest AI news', 'market analysis'). JARVIS will search the web and write a detailed long-form email."
            },
            "message_id": {
                "type": "STRING",
                "description": "Optional specific Gmail message ID for read_email or reply_to_email."
            },
            "thread_id": {
                "type": "STRING",
                "description": "Optional specific Gmail thread ID for reply_to_email."
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
