"""Send a fake Messenger conversation to your LOCAL app, signed like Meta does. No Meta account needed.

Use it to check the pipeline before involving Meta:

    python -m scripts.send_test_message                      # a guest message, then a staff reply 3 minutes later
    python -m scripts.send_test_message --text "Hi, available po sa Oct 18? 4 pax"
    python -m scripts.send_test_message --url http://localhost:8000 --no-reply

Then run:  python -m scripts.show_recent --client my-airbnb
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid

import httpx

import app  # noqa: F401  (loads poc/.env)


def send(url: str, secret: str, payload: dict) -> httpx.Response:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return httpx.post(url.rstrip("/") + "/webhooks/meta", content=body,
                      headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"}, timeout=15)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--text", default="Hi! Available po ba sa Oct 18-19? 4 pax kami. Magkano po?")
    ap.add_argument("--reply-text", default="Hello po! Yes available. 4,500 per night.")
    ap.add_argument("--no-reply", action="store_true")
    ap.add_argument("--guest", default="TEST_GUEST_" + uuid.uuid4().hex[:6])
    args = ap.parse_args()

    secret, page = os.environ.get("META_APP_SECRET"), os.environ.get("META_PAGE_ID")
    if not secret or not page:
        print("Set META_APP_SECRET and META_PAGE_ID in poc/.env first.")
        return 1
    now = int(time.time() * 1000)

    inbound = {"object": "page", "entry": [{"id": page, "time": now, "messaging": [{
        "sender": {"id": args.guest}, "recipient": {"id": page}, "timestamp": now - 3 * 60_000,
        "message": {"mid": "test_" + uuid.uuid4().hex, "text": args.text}}]}]}
    try:
        r = send(args.url, secret, inbound)
    except httpx.ConnectError:
        print(f"Could not reach {args.url}. Start the app first (Run and Debug → App: run the webhook server).")
        return 3
    print("guest message ->", r.status_code, r.text)
    if r.status_code == 403:
        print("403: the signature was rejected. META_APP_SECRET in .env must match the one the app was started with. Restart the app after editing .env.")
        return 2
    if r.status_code != 200:
        return 2

    if not args.no_reply:
        echo = {"object": "page", "entry": [{"id": page, "time": now, "messaging": [{
            "sender": {"id": page}, "recipient": {"id": args.guest}, "timestamp": now,
            "message": {"mid": "test_" + uuid.uuid4().hex, "is_echo": True, "app_id": "263902037430900", "text": args.reply_text}}]}]}
        r = send(args.url, secret, echo)
        print("staff reply   ->", r.status_code, r.text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
