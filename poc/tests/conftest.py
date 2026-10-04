import hashlib
import hmac
import json
import os

import pytest

# Must be set before app.main is imported (it connects at import time).
os.environ.setdefault("DATABASE_URL", "postgresql://postgres@/revobs_test?host=/var/tmp/pgpoc&port=5433")
os.environ["META_APP_SECRET"] = "test-secret"
os.environ["META_VERIFY_TOKEN"] = "test-verify"
os.environ["META_PAGE_ID"] = "PAGE_TEST_1"
os.environ["META_APP_ID"] = "APP_AI_1"
os.environ.pop("META_PAGE_TOKEN", None)
os.environ.pop("META_PAGE_TOKENS", None)

import psycopg  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


@pytest.fixture()
def db():
    from app.db import connect
    with connect() as c:
        for t in ("alerts", "lead_labels", "events", "messages", "leads", "raw_webhooks"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
        yield c


def sign(body: bytes) -> dict:
    sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": sig, "Content-Type": "application/json"}


def post(client, payload: dict):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/meta", content=body, headers=sign(body))


def page_event(ts_ms: int, *, mid: str, customer="PSID_ANA", text="hi", echo_app=None, referral=None, page="PAGE_TEST_1"):
    """Payload shaped like Meta's Messenger webhook (object=page)."""
    if echo_app:
        ev = {"sender": {"id": page}, "recipient": {"id": customer}, "timestamp": ts_ms,
              "message": {"mid": mid, "is_echo": True, "app_id": echo_app, "text": text}}
    else:
        ev = {"sender": {"id": customer}, "recipient": {"id": page}, "timestamp": ts_ms, "message": {"mid": mid, "text": text}}
        if referral:
            ev["referral"] = referral
    return {"object": "page", "entry": [{"id": page, "time": ts_ms, "messaging": [ev]}]}
