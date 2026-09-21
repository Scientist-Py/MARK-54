"""
actions/google_contacts.py — Headless Google Contacts Integration for JARVIS
Searches contacts by name, nickname, or organization. Returns phone numbers, email addresses,
and contact metadata to power WhatsApp, phone dialing, and Gmail recipient resolution.
"""

from __future__ import annotations

import os
import sys
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


def _get_people_service():
    creds = get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        return build("people", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"[Contacts] ❌ Service build error: {e}")
        return None


def search_contacts(query: str, max_results: int = 10) -> list[dict]:
    """Search contacts by query string (name, phone, email)."""
    service = _get_people_service()
    if not service:
        return []

    results = []
    try:
        resp = service.people().searchContacts(
            query=query,
            readMask="names,emailAddresses,phoneNumbers,organizations,birthdays,biographies",
            pageSize=max_results,
        ).execute()

        for item in resp.get("results", []):
            person = item.get("person", {})
            name = ""
            names = person.get("names", [])
            if names:
                name = names[0].get("displayName", "")

            emails = [e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")]
            phones = [p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")]
            orgs = [o.get("name", "") for o in person.get("organizations", []) if o.get("name")]

            results.append({
                "name": name,
                "emails": emails,
                "phones": phones,
                "organizations": orgs,
            })
    except Exception as e:
        print(f"[Contacts] ⚠️ Search error: {e}")

    # Fallback to connections list if searchContacts returns empty or restricted
    if not results:
        try:
            resp = service.people().connections().list(
                resourceName="people/me",
                pageSize=100,
                personFields="names,emailAddresses,phoneNumbers,organizations",
            ).execute()
            q_lower = query.lower().strip()
            for person in resp.get("connections", []):
                names = person.get("names", [])
                name = names[0].get("displayName", "") if names else ""
                if q_lower in name.lower():
                    emails = [e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")]
                    phones = [p.get("value", "") for p in person.get("phoneNumbers", []) if p.get("value")]
                    orgs = [o.get("name", "") for o in person.get("organizations", []) if o.get("name")]
                    results.append({
                        "name": name,
                        "emails": emails,
                        "phones": phones,
                        "organizations": orgs,
                    })
        except Exception as e:
            print(f"[Contacts] ⚠️ List fallback error: {e}")

    return results


def google_contacts_action(
    parameters: dict,
    player=None,
    speak=None,
    session_memory=None,
    **kwargs
) -> str:
    action = (parameters.get("action") or "search").lower().strip()
    query  = (parameters.get("query") or parameters.get("name") or "").strip()

    if not query and action in ("search", "get_phone", "get_email", "lookup"):
        return "Sir, please specify the contact name or query you want to find."

    service = _get_people_service()
    if not service:
        return "Sir, Google Contacts is not authenticated. Please run Google Sign-In or check config/credentials.json."

    contacts = search_contacts(query, max_results=8)
    if not contacts:
        return f"Sir, I could not find any contact matching '{query}' in your Google Contacts."

    # Handle phone number query
    if action in ("get_phone", "phone", "number"):
        found = []
        for c in contacts:
            if c.get("phones"):
                phones_str = ", ".join(c["phones"])
                found.append(f"{c['name']}: {phones_str}")
        if found:
            res_str = "\n".join(found)
            if player and hasattr(player, "show_content"):
                player.show_content(f"CONTACT NUMBER: {query.upper()}", res_str)
            return f"Sir, here is the phone number for {contacts[0]['name']}: {', '.join(contacts[0]['phones'])}."
        return f"Sir, I found {contacts[0]['name']}, but no phone number is listed in their contact details."

    # Handle email address query
    if action in ("get_email", "email"):
        found = []
        for c in contacts:
            if c.get("emails"):
                emails_str = ", ".join(c["emails"])
                found.append(f"{c['name']}: {emails_str}")
        if found:
            res_str = "\n".join(found)
            if player and hasattr(player, "show_content"):
                player.show_content(f"CONTACT EMAIL: {query.upper()}", res_str)
            return f"Sir, the email address for {contacts[0]['name']} is {contacts[0]['emails'][0]}."
        return f"Sir, I found {contacts[0]['name']}, but no email address is listed."

    # Default: search summary
    lines = []
    for idx, c in enumerate(contacts, 1):
        phones = f"Phone: {', '.join(c['phones'])}" if c.get("phones") else "No phone"
        emails = f"Email: {', '.join(c['emails'])}" if c.get("emails") else "No email"
        org = f" ({', '.join(c['organizations'])})" if c.get("organizations") else ""
        lines.append(f"{idx}. {c['name']}{org}\n   {phones} | {emails}")

    card_text = "\n\n".join(lines)
    if player and hasattr(player, "show_content"):
        player.show_content(f"GOOGLE CONTACTS: {query.upper()}", card_text)

    top = contacts[0]
    top_detail = []
    if top.get("phones"):
        top_detail.append(f"phone {top['phones'][0]}")
    if top.get("emails"):
        top_detail.append(f"email {top['emails'][0]}")

    detail_str = f" with {', '.join(top_detail)}" if top_detail else ""
    return f"Sir, I found {top['name']}{detail_str}. Full details are displayed on your HUD."


TOOL = {
    "name": "google_contacts",
    "description": (
        "Search and look up personal contacts from Google Contacts (People API). "
        "Find phone numbers, email addresses, and details for friends, family, or colleagues "
        "to assist with WhatsApp calling, messaging, or sending Gmails."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["search", "get_phone", "get_email", "lookup"],
                "description": "Action: 'search' for full contact summary, 'get_phone' for phone number, 'get_email' for email address."
            },
            "query": {
                "type": "STRING",
                "description": "Name, nickname, or search term for the contact (e.g. 'Rahul', 'Puneet', 'Dad')."
            }
        },
        "required": ["query"]
    },
    "handler": google_contacts_action,
}
