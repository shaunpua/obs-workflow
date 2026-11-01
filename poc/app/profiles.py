"""Fill in customer names for Messenger leads.

Meta's webhooks only carry an id (PSID), not a name. We fetch it once from the
User Profile API and store it. This runs after the webhook has been answered,
and any failure is logged and ignored so it can never block ingestion.
"""
from __future__ import annotations

import json
import logging
import os
import time

import httpx

from .db import connect

log = logging.getLogger("profiles")
GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v23.0")


def page_token(page_id: str) -> str | None:
    """Token for a Page: META_PAGE_TOKENS (JSON {page_id: token}) or META_PAGE_TOKEN for a single Page."""
    try:
        tokens = json.loads(os.environ.get("META_PAGE_TOKENS", "{}"))
    except json.JSONDecodeError:
        tokens = {}
    return tokens.get(page_id) or os.environ.get("META_PAGE_TOKEN")


_retry_after: dict[str, float] = {}   # psid -> time before which we don't ask Meta again (stops a retry on every webhook)
RETRY_SECONDS = 600


def fetch_profile(psid: str, token: str, page_id: str | None = None) -> dict | None:
    """Name for a PSID. Tries the User Profile API, then the Page's conversations list.

    The per-user lookup is often refused (permission/app-mode), while the conversations
    endpoint works with the plain pages_messaging token and returns the participant's name.
    """
    r = httpx.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{psid}",
                  params={"fields": "first_name,last_name,profile_pic", "access_token": token}, timeout=10)
    if r.status_code == 200:
        return r.json()
    if page_id:
        r2 = httpx.get(f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/conversations",
                       params={"user_id": psid, "fields": "participants", "access_token": token}, timeout=10)
        if r2.status_code == 200:
            for conv in r2.json().get("data", []):
                for person in conv.get("participants", {}).get("data", []):
                    if str(person.get("id")) == str(psid) and person.get("name"):
                        return {"first_name": person["name"]}
    log.warning("name lookup for %s failed: %s %s", psid, r.status_code, r.text[:120])
    return None


def fill_missing_names(limit: int = 20) -> int:
    """Look up names for Messenger leads that don't have one yet. Returns how many were filled."""
    filled = 0
    try:
        with connect() as conn:
            rows = conn.execute(
                """SELECT l.lead_id, l.external_user_id, c.external_id AS page_id
                     FROM leads l JOIN channels c ON c.client_id = l.client_id AND c.channel = 'messenger'
                    WHERE l.channel = 'messenger' AND l.display_name IS NULL
                    ORDER BY l.created_at DESC LIMIT %s""", (limit,)).fetchall()
            for row in rows:
                token = page_token(row["page_id"])
                if not token or _retry_after.get(row["external_user_id"], 0) > time.time():
                    continue
                prof = fetch_profile(row["external_user_id"], token, row["page_id"])
                if not prof:
                    _retry_after[row["external_user_id"]] = time.time() + RETRY_SECONDS
                    continue
                name = " ".join(x for x in (prof.get("first_name"), prof.get("last_name")) if x)
                if name:
                    conn.execute("UPDATE leads SET display_name=%s WHERE lead_id=%s", (name, row["lead_id"]))
                    filled += 1
            conn.commit()
    except Exception:
        log.exception("name lookup failed")
    return filled
