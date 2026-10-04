"""Subscribe your Facebook Page to the webhook fields this app needs, or check the current subscription.

    export META_PAGE_ID=...        # your Page id
    export META_PAGE_TOKEN=...     # Page access token (Graph API Explorer or the Messenger product page)
    python -m scripts.subscribe_page            # subscribe
    python -m scripts.subscribe_page --check    # show what is subscribed now

The Page must already be added to your Meta app (Messenger → Settings → add the Page).
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

GRAPH_VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
FIELDS = "messages,message_echoes,messaging_postbacks,messaging_referrals,message_reads,message_deliveries"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only show the current subscription")
    args = ap.parse_args()

    page_id, token = os.environ.get("META_PAGE_ID"), os.environ.get("META_PAGE_TOKEN")
    if not page_id or not token:
        print("Set META_PAGE_ID and META_PAGE_TOKEN first.")
        return 1
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/subscribed_apps"
    if args.check:
        r = httpx.get(url, params={"access_token": token}, timeout=15)
    else:
        r = httpx.post(url, params={"subscribed_fields": FIELDS, "access_token": token}, timeout=15)
    print(r.status_code, r.text)
    return 0 if r.status_code == 200 else 2


if __name__ == "__main__":
    sys.exit(main())
