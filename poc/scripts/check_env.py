"""Check your local setup and say exactly what is missing. Safe to run any time; it never prints secrets.

    python -m scripts.check_env
    python -m scripts.check_env --url https://your-tunnel.trycloudflare.com    # also test the public URL
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

import app  # noqa: F401  (loads poc/.env)

OK, BAD, WARN = "  ok   ", "  FIX  ", "  note "


def line(tag: str, text: str) -> None:
    print(f"{tag} {text}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="public tunnel URL, to test Meta's verification handshake")
    args = ap.parse_args()
    problems = 0

    print("\n1. Environment (.env)")
    required = {
        "DATABASE_URL": "postgresql://revobs:revobs@localhost:5432/revobs",
        "META_APP_ID": "App settings → Basic → App ID",
        "META_APP_SECRET": "App settings → Basic → App Secret (click Show)",
        "META_VERIFY_TOKEN": "any string you choose; you type the same one into Meta's webhook settings",
        "META_PAGE_ID": "your Page's numeric ID",
        "META_PAGE_TOKEN": "Messenger settings → Generate token for your Page",
    }
    for name, hint in required.items():
        v = os.environ.get(name, "")
        if v and v not in ("change-me", "dev-secret"):
            line(OK, f"{name} is set")
        else:
            problems += 1
            line(BAD, f"{name} is missing. Where to find it: {hint}")

    print("\n2. Database")
    try:
        from app.db import connect

        with connect() as c:
            c.execute("SELECT 1")
        line(OK, "connected to Postgres")
    except Exception as exc:
        problems += 1
        line(BAD, f"cannot connect: {str(exc).splitlines()[0]}. Is it running? Try: docker compose up -d db")

    print("\n3. Facebook Page token")
    page_id, token = os.environ.get("META_PAGE_ID"), os.environ.get("META_PAGE_TOKEN")
    if page_id and token:
        ver = os.environ.get("GRAPH_VERSION", "v23.0")
        try:
            r = httpx.get(f"https://graph.facebook.com/{ver}/{page_id}", params={"fields": "name", "access_token": token}, timeout=15)
            if r.status_code == 200:
                line(OK, f"token works for Page: {r.json().get('name')}")
            else:
                problems += 1
                msg = r.json().get("error", {}).get("message", r.text[:150])
                line(BAD, f"Meta rejected the token or Page ID: {msg}")
        except Exception as exc:
            line(WARN, f"could not reach Meta: {exc}")
    else:
        line(WARN, "skipped (needs META_PAGE_ID and META_PAGE_TOKEN)")

    if args.url:
        print("\n4. Public URL")
        try:
            r = httpx.get(args.url.rstrip("/") + "/webhooks/meta", params={
                "hub.mode": "subscribe", "hub.verify_token": os.environ.get("META_VERIFY_TOKEN", ""), "hub.challenge": "ping123"}, timeout=15)
            if r.status_code == 200 and r.text == "ping123":
                line(OK, "the tunnel reaches your app and the verify token matches. Meta's 'Verify and save' will pass")
            else:
                problems += 1
                line(BAD, f"got HTTP {r.status_code}. Is uvicorn running, and does META_VERIFY_TOKEN match? (restart uvicorn after editing .env)")
        except Exception as exc:
            problems += 1
            line(BAD, f"cannot reach {args.url}: {exc}")

    print("\nAll good." if not problems else f"\n{problems} thing(s) to fix above.")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
