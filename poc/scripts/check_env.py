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
        "DATABASE_URL": "postgresql://revobs:revobs@localhost:55432/revobs",
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
    app_id, app_secret = os.environ.get("META_APP_ID"), os.environ.get("META_APP_SECRET")
    if page_id and token and app_id and app_secret:
        ver = os.environ.get("GRAPH_VERSION", "v23.0")
        try:
            # debug_token needs no extra permission (unlike reading the Page's name)
            r = httpx.get(f"https://graph.facebook.com/{ver}/debug_token",
                          params={"input_token": token, "access_token": f"{app_id}|{app_secret}"}, timeout=15)
            d = r.json().get("data") if r.status_code == 200 else None
            if d is None:
                problems += 1
                msg = r.json().get("error", {}).get("message", r.text[:150])
                line(BAD, f"Meta rejected the check (is META_APP_ID / META_APP_SECRET right?): {msg}")
            elif not d.get("is_valid"):
                problems += 1
                line(BAD, f"the token is not valid: {d.get('error', {}).get('message', 'regenerate it in Messenger API settings')}")
            elif d.get("type") != "PAGE":
                problems += 1
                line(BAD, f"this is a {d.get('type')} token, not a Page token. Use Messenger API settings -> Generate token")
            elif str(d.get("profile_id")) != str(page_id):
                problems += 1
                line(BAD, f"the token belongs to Page {d.get('profile_id')}, but META_PAGE_ID is {page_id}. Use {d.get('profile_id')}")
            else:
                scopes = d.get("scopes", [])
                line(OK, f"token is a valid Page token for Page {page_id} (permissions: {', '.join(scopes)})")
                if "pages_messaging" not in scopes:
                    problems += 1
                    line(BAD, "the token lacks pages_messaging. Regenerate it after adding the Messenger use case")
        except Exception as exc:
            line(WARN, f"could not reach Meta: {exc}")
    else:
        line(WARN, "skipped (needs META_PAGE_ID, META_PAGE_TOKEN, META_APP_ID and META_APP_SECRET)")

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
