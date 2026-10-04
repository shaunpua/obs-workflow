"""Webhook receiver + small API.

Run:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import alerts, pipeline
from .config import load_all_clients, sync_clients_to_db
from .db import connect, migrate
from .normalize import normalize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("revobs")

META_APP_SECRET = os.environ.get("META_APP_SECRET", "dev-secret")
META_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "dev-verify")
API_KEY = os.environ.get("API_KEY", "dev-api-key")

app = FastAPI(title="Revenue Observability POC")
conn = connect()
migrate(conn)
CLIENTS = load_all_clients()
sync_clients_to_db(conn, CLIENTS)


def _check_api_key(key: str | None):
    if key != API_KEY:
        raise HTTPException(401, "bad api key")


def _store_raw(source: str, payload: dict, signature_ok: bool | None) -> int:
    row = conn.execute("INSERT INTO raw_webhooks (source, payload, signature_ok) VALUES (%s,%s,%s) RETURNING id",
                       (source, json.dumps(payload), signature_ok)).fetchone()
    conn.commit()
    return row["id"]


def _process(source: str, raw_id: int, payload: dict) -> dict:
    results = {}
    try:
        for m in normalize(source, payload):
            r = pipeline.ingest_message(conn, CLIENTS, m, raw_id)
            results[r] = results.get(r, 0) + 1
        conn.execute("UPDATE raw_webhooks SET processed_at=now() WHERE id=%s", (raw_id,))
    except Exception as exc:  # keep the raw payload; re-process later
        conn.rollback()
        log.exception("processing failed for raw %s", raw_id)
        conn.execute("UPDATE raw_webhooks SET error=%s WHERE id=%s", (str(exc), raw_id))
    conn.commit()
    return results


# ------------------------------------------------------------------ Meta
@app.get("/webhooks/meta", response_class=PlainTextResponse)
def meta_verify(mode: str = Query(alias="hub.mode"), token: str = Query(alias="hub.verify_token"),
                challenge: str = Query(alias="hub.challenge")):
    """Meta calls this once when you register the webhook URL in the app dashboard."""
    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return challenge
    raise HTTPException(403)


@app.post("/webhooks/meta")
async def meta_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None)):
    """Messenger, Instagram and WhatsApp all arrive here, signed with your app secret."""
    body = await request.body()
    expected = "sha256=" + hmac.new(META_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(403, "bad signature")
    payload = json.loads(body)
    raw_id = _store_raw("meta", payload, True)
    # POC processes inline. In production: enqueue raw_id and return 200 immediately.
    return {"ok": True, "results": _process("meta", raw_id, payload)}


# ------------------------------------------------------------------ Chatwoot
@app.post("/webhooks/chatwoot")
async def chatwoot_webhook(request: Request, token: str = Query()):
    _check_api_key(token)
    payload = await request.json()
    raw_id = _store_raw("chatwoot", payload, None)
    return {"ok": True, "results": _process("chatwoot", raw_id, payload)}


# ------------------------------------------------------------------ business events
class LeadRef(BaseModel):
    client_id: str
    channel: str
    external_user_id: str


class BusinessEvent(BaseModel):
    lead: LeadRef
    event_type: str                 # consult_booked, appointment_showed, payment_received ...
    occurred_at: datetime
    value: float | None = None
    props: dict = {}
    dedupe_key: str | None = None


@app.post("/api/events")
def business_event(ev: BusinessEvent, x_api_key: str | None = Header(default=None)):
    """Bookings (Cal.com), payments (PayMongo), or a staff 'Arrived' button post here."""
    _check_api_key(x_api_key)
    lead = conn.execute("SELECT lead_id FROM leads WHERE client_id=%s AND channel=%s AND external_user_id=%s",
                        (ev.lead.client_id, ev.lead.channel, ev.lead.external_user_id)).fetchone()
    if not lead:
        raise HTTPException(404, "lead not found")
    pipeline.record_business_event(conn, CLIENTS, ev.lead.client_id, lead["lead_id"], ev.event_type,
                                   ev.occurred_at, ev.value, ev.props, dedupe_key=ev.dedupe_key)
    return {"ok": True}


@app.post("/api/tick")
def tick(as_of: datetime | None = None, x_api_key: str | None = Header(default=None)):
    """Run alert checks. Call every minute from cron/n8n. `as_of` lets the simulator replay time."""
    _check_api_key(x_api_key)
    return alerts.run_checks(conn, CLIENTS, as_of or datetime.now(timezone.utc))


@app.get("/api/leads")
def leads(client_id: str, x_api_key: str | None = Header(default=None)):
    _check_api_key(x_api_key)
    return conn.execute("""SELECT lead_id, display_name, channel, stage, temperature, score, intent, interest,
                                  est_value, next_action, next_action_priority, awaiting_reply, waiting_since
                             FROM leads WHERE client_id=%s ORDER BY next_action_priority, waiting_since NULLS LAST""",
                        (client_id,)).fetchall()


@app.get("/api/leads/{lead_id}/trace")
def trace(lead_id: str, x_api_key: str | None = Header(default=None)):
    _check_api_key(x_api_key)
    return pipeline.lead_trace(conn, lead_id)


@app.get("/health")
def health():
    return {"ok": True, "clients": list(CLIENTS)}
