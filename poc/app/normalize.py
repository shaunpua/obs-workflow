"""Turn each platform's webhook shape into one canonical message shape.

Every adapter returns a list of dicts like:
    {channel, channel_external_id, customer_id, customer_name, direction ('in'|'out'),
     message_id, sent_at (datetime, UTC), text, app_id, referral {ad_id, source} | None}

Adding a new channel (Viber Business, TikTok, Chatwoot, a web chat) means writing
one more adapter. Nothing downstream changes.
"""
from __future__ import annotations

from datetime import datetime, timezone


def _ts_ms(ms) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _ts_s(s) -> datetime:
    return datetime.fromtimestamp(int(s), tz=timezone.utc)


def _referral(obj: dict | None) -> dict | None:
    if not obj:
        return None
    return {"ad_id": obj.get("ad_id") or obj.get("source_id"), "source": (obj.get("source") or obj.get("source_type") or "").lower()}


def from_meta_messaging(payload: dict) -> list[dict]:
    """Messenger (object=page) and Instagram (object=instagram) DMs, incl. echoes."""
    channel = "messenger" if payload.get("object") == "page" else "instagram"
    out = []
    for entry in payload.get("entry", []):
        account_id = entry["id"]
        for ev in entry.get("messaging", []):
            msg = ev.get("message")
            if not msg:            # reads, deliveries, postbacks: ignored in the POC
                continue
            is_echo = bool(msg.get("is_echo"))
            out.append({
                "channel": channel,
                "channel_external_id": account_id,
                "customer_id": ev["recipient"]["id"] if is_echo else ev["sender"]["id"],
                "customer_name": None,
                "direction": "out" if is_echo else "in",
                "message_id": msg["mid"],
                "sent_at": _ts_ms(ev["timestamp"]),
                "text": msg.get("text", ""),
                "app_id": str(msg["app_id"]) if msg.get("app_id") else None,
                # click-to-message ads put the ad id on the first message
                "referral": _referral(ev.get("referral") or msg.get("referral")),
            })
    return out


def from_whatsapp(payload: dict) -> list[dict]:
    """WhatsApp Cloud API: customer messages + smb_message_echoes (Coexistence)."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = value.get("metadata", {}).get("phone_number_id")
            names = {c["wa_id"]: c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            if change.get("field") == "messages":
                for m in value.get("messages", []):
                    out.append({
                        "channel": "whatsapp", "channel_external_id": pnid,
                        "customer_id": m["from"], "customer_name": names.get(m["from"]),
                        "direction": "in", "message_id": m["id"], "sent_at": _ts_s(m["timestamp"]),
                        "text": (m.get("text") or {}).get("body", f"[{m.get('type')}]"),
                        "app_id": None, "referral": _referral(m.get("referral")),
                    })
            elif change.get("field") == "smb_message_echoes":
                # Staff replied from the WhatsApp Business phone app.
                for m in value.get("message_echoes", []):
                    out.append({
                        "channel": "whatsapp", "channel_external_id": pnid,
                        "customer_id": m["to"], "customer_name": None,
                        "direction": "out", "message_id": m["id"], "sent_at": _ts_s(m["timestamp"]),
                        "text": (m.get("text") or {}).get("body", ""),
                        "app_id": "WA_BUSINESS_APP", "referral": None,
                    })
    return out


def from_chatwoot(payload: dict) -> list[dict]:
    """Chatwoot `message_created` webhook (one shape for every inbox it connects)."""
    if payload.get("event") != "message_created" or payload.get("private"):
        return []
    conv = payload.get("conversation", {})
    contact = conv.get("meta", {}).get("sender", {}) or payload.get("sender", {})
    incoming = payload.get("message_type") == "incoming"
    return [{
        "channel": "chatwoot",
        "channel_external_id": str(payload.get("inbox", {}).get("id")),
        "customer_id": str(contact.get("id")),
        "customer_name": contact.get("name"),
        "direction": "in" if incoming else "out",
        "message_id": f"cw_{payload['id']}",
        "sent_at": datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00")),
        "text": payload.get("content") or "",
        "app_id": "AI" if (payload.get("content_attributes") or {}).get("ai_generated") else "CHATWOOT_AGENT",
        "referral": None,
    }]


def normalize(source: str, payload: dict) -> list[dict]:
    if source == "meta":
        if payload.get("object") in ("page", "instagram"):
            return from_meta_messaging(payload)
        if payload.get("object") == "whatsapp_business_account":
            return from_whatsapp(payload)
        return []
    if source == "chatwoot":
        return from_chatwoot(payload)
    raise ValueError(f"unknown source {source}")
