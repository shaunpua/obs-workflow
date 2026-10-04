"""Print what the app has received, so you can check the two timestamps landed.

    python -m scripts.show_recent                     # all clients, last 15 messages
    python -m scripts.show_recent --client my-airbnb  # one client
    python -m scripts.show_recent --raw               # also show the last raw webhooks (and any errors)
"""
from __future__ import annotations

import argparse

from app.db import connect


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--raw", action="store_true")
    args = ap.parse_args()

    try:
        c = connect()
    except Exception as exc:
        print(f"Cannot connect to the database: {str(exc).splitlines()[0]}\nIs it running? Try: docker compose up -d db")
        raise SystemExit(1)
    with c:
        where, params = ("WHERE m.client_id = %s", [args.client]) if args.client else ("", [])
        rows = c.execute(
            f"""SELECT m.sent_at AT TIME ZONE 'Asia/Manila' AS t, m.client_id, COALESCE(l.display_name, l.external_user_id) AS who,
                       m.direction, m.actor, left(m.body, 60) AS body
                  FROM messages m JOIN leads l USING (lead_id) {where} ORDER BY m.sent_at DESC LIMIT %s""",
            params + [args.limit]).fetchall()
        print("\nLATEST MESSAGES (Manila time)")
        for r in reversed(rows):
            arrow = "→ customer" if r["direction"] == "out" else "← customer"
            print(f"  {r['t']:%m-%d %H:%M:%S}  {r['client_id']:<14} {str(r['who'])[:18]:<18} {arrow:<11} {r['actor']:<8} {r['body'] or ''}")

        pairs = c.execute(
            f"""SELECT p.client_id, COALESCE(l.display_name, l.external_user_id) AS who, p.asked_at AT TIME ZONE 'Asia/Manila' AS asked,
                       p.replied_by, p.raw_minutes, p.business_minutes, p.is_first_response
                  FROM v_reply_pairs p JOIN leads l USING (lead_id) {where.replace('m.', 'p.')}
                 ORDER BY p.asked_at DESC LIMIT %s""", params + [args.limit]).fetchall()
        print("\nREPLY TIMES")
        for r in reversed(pairs):
            reply = f"{r['raw_minutes']} min raw / {r['business_minutes']} min in hours, by {r['replied_by']}" if r["replied_by"] else "NO REPLY YET"
            print(f"  {r['asked']:%m-%d %H:%M}  {str(r['who'])[:18]:<18} {'first' if r['is_first_response'] else 'turn '}  {reply}")

        leads = c.execute(f"""SELECT COALESCE(display_name, external_user_id) AS who, temperature, score, intent, stage, next_action
                               FROM leads {where.replace('m.', '')} ORDER BY updated_at DESC LIMIT %s""", params + [args.limit]).fetchall()
        print("\nLEADS")
        for r in leads:
            print(f"  {str(r['who'])[:18]:<18} {str(r['temperature']):<5} score={r['score']} {str(r['intent']):<22} {r['stage']:<10} → {r['next_action']}")

        if args.raw:
            raws = c.execute("SELECT id, received_at, signature_ok, processed_at IS NOT NULL AS done, error FROM raw_webhooks ORDER BY id DESC LIMIT 10").fetchall()
            print("\nRAW WEBHOOKS")
            for r in reversed(raws):
                print(f"  #{r['id']} {r['received_at']:%m-%d %H:%M:%S} signed={r['signature_ok']} processed={r['done']} {r['error'] or ''}")
        print()


if __name__ == "__main__":
    main()
