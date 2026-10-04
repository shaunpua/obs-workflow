"""Alert checks. Run every minute (cron, n8n schedule, or POST /api/tick).

- hot_unanswered: a hot lead has waited longer than the SLA (business hours only)
- escalation:     any lead has waited past the escalation SLA -> manager
- integration_silent: no webhooks for N hours during business hours -> YOU
  (usually a revoked token, not a quiet day)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import httpx

from .pipeline import refresh_lead

log = logging.getLogger("alerts")


def notify(cfg: dict, who: str, text: str) -> None:
    target = (cfg.get("alerts") or {}).get(who, {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get(target.get("chat_id_env", ""), "")
    if os.environ.get("NOTIFY", "console") == "telegram" and token and chat_id:
        httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
    else:
        log.info("[%s -> %s] %s", cfg["client_id"], who, text)


def _fire(conn, cfg, lead, alert_type, now, who, text) -> bool:
    row = conn.execute(
        """INSERT INTO alerts (client_id, lead_id, alert_type, fired_at, message) VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (lead_id, alert_type) WHERE resolved_at IS NULL DO NOTHING RETURNING id""",
        (cfg["client_id"], lead["lead_id"], alert_type, now, text)).fetchone()
    if row:
        conn.execute("""INSERT INTO events (client_id, lead_id, event_type, occurred_at, actor, props)
                        VALUES (%s,%s,'alert_fired',%s,'system',jsonb_build_object('type',%s::text,'to',%s::text))""",
                     (cfg["client_id"], lead["lead_id"], now, alert_type, who))
        notify(cfg, who, text)
    return bool(row)


def run_checks(conn, clients: dict, now: datetime) -> dict:
    fired = {"hot_unanswered": 0, "escalation": 0, "integration_silent": 0}
    for client_id, cfg in clients.items():
        sla = cfg["sla"]
        waiting = conn.execute(
            """SELECT l.*, business_minutes(l.client_id, l.waiting_since, %s) AS waited_bmin
                 FROM leads l WHERE l.client_id=%s AND l.awaiting_reply AND l.waiting_since <= %s""",
            (now, client_id, now)).fetchall()
        for lead in waiting:
            lead = {**lead, **refresh_lead(conn, cfg, lead["lead_id"], now)}
            waited = float(lead["waited_bmin"] or 0)
            name = lead["display_name"] or lead["external_user_id"][-4:]
            if lead["temperature"] == "hot" and waited >= sla["hot_unanswered_alert_minutes"]:
                if _fire(conn, cfg, lead, "hot_unanswered", now, "front_desk",
                         f"HOT lead waiting {waited:.0f} min on {lead['channel']}: {name} "
                         f"({lead['interest'] or 'unknown'}). {lead['next_action']}"):
                    fired["hot_unanswered"] += 1
            if waited >= sla["escalation_minutes"]:
                if _fire(conn, cfg, lead, "escalation", now, "manager",
                         f"Unanswered {waited:.0f} business min: {name} on {lead['channel']}"):
                    fired["escalation"] += 1

        in_hours = conn.execute("SELECT in_business_hours(%s, %s) AS ok", (client_id, now)).fetchone()["ok"]
        last = conn.execute("SELECT max(sent_at) AS t FROM messages WHERE client_id=%s AND sent_at <= %s",
                            (client_id, now)).fetchone()["t"]
        if in_hours and last and (now - last).total_seconds() > 6 * 3600:
            log.warning("[%s] no messages for 6h during business hours: check tokens/webhooks", client_id)
            fired["integration_silent"] += 1
    conn.commit()
    return fired
