"""The processing pipeline: canonical message/event -> lead DB, traces, labels, actions.

    webhook -> normalize -> ingest_message() -> [lead upsert, message log,
                 events (trace spans), classification, stage, next action]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .classify import llm_classify, rule_classify

log = logging.getLogger("pipeline")


def client_for_channel(conn, channel: str, external_id: str) -> str | None:
    row = conn.execute("SELECT client_id FROM channels WHERE channel=%s AND external_id=%s",
                       (channel, external_id)).fetchone()
    return row["client_id"] if row else None


def add_event(conn, client_id, lead_id, event_type, occurred_at, actor=None, value=None, props=None, dedupe_key=None):
    conn.execute(
        """INSERT INTO events (client_id, lead_id, event_type, occurred_at, actor, value, props, dedupe_key)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING""",
        (client_id, lead_id, event_type, occurred_at, actor, value, json.dumps(props or {}), dedupe_key),
    )


def _get_or_create_lead(conn, client_id, m) -> tuple[dict, bool]:
    referral = m.get("referral")
    row = conn.execute(
        """INSERT INTO leads (client_id, channel, external_user_id, display_name, created_at, first_source, first_ad_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (client_id, channel, external_user_id) DO NOTHING RETURNING *""",
        (client_id, m["channel"], m["customer_id"], m.get("customer_name"), m["sent_at"],
         "ad" if referral and referral.get("ad_id") else "organic", (referral or {}).get("ad_id")),
    ).fetchone()
    if row:
        add_event(conn, client_id, row["lead_id"], "lead_created", m["sent_at"], actor="customer",
                  props={"channel": m["channel"], "ad_id": (referral or {}).get("ad_id")},
                  dedupe_key=f"created:{row['lead_id']}")
        return row, True
    row = conn.execute("SELECT * FROM leads WHERE client_id=%s AND channel=%s AND external_user_id=%s",
                       (client_id, m["channel"], m["customer_id"])).fetchone()
    return row, False


def ingest_message(conn, clients: dict, m: dict, raw_id: int | None = None) -> str:
    client_id = client_for_channel(conn, m["channel"], m["channel_external_id"])
    if not client_id:
        log.warning("webhook for unknown %s id %r: add it to a client file under channels.%s.external_id",
                    m["channel"], m["channel_external_id"], m["channel"])
        return "unknown_channel"
    cfg = clients[client_id]
    lead, _ = _get_or_create_lead(conn, client_id, m)

    if m["direction"] == "in":
        actor = "customer"
    else:
        actor = "ai" if m.get("app_id") and m["app_id"] == cfg.get("ai_app_id") else "staff"

    inserted = conn.execute(
        """INSERT INTO messages (message_id, client_id, lead_id, channel, direction, actor, sent_at, body, app_id, raw_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (message_id) DO NOTHING RETURNING message_id""",
        (m["message_id"], client_id, lead["lead_id"], m["channel"], m["direction"], actor, m["sent_at"],
         m.get("text"), m.get("app_id"), raw_id),
    ).fetchone()
    if not inserted:
        conn.commit()
        return "duplicate"   # Meta retries deliveries; the message id makes this idempotent

    if m["direction"] == "out":
        had_inbound = conn.execute("SELECT 1 FROM messages WHERE lead_id=%s AND direction='in' AND sent_at < %s LIMIT 1",
                                   (lead["lead_id"], m["sent_at"])).fetchone()
        if had_inbound:
            add_event(conn, client_id, lead["lead_id"], "first_reply", m["sent_at"], actor=actor,
                      dedupe_key=f"first_reply:{lead['lead_id']}")
        conn.execute("UPDATE alerts SET resolved_at=%s WHERE lead_id=%s AND resolved_at IS NULL",
                     (m["sent_at"], lead["lead_id"]))

    refresh_lead(conn, cfg, lead["lead_id"], now=m["sent_at"], new_inbound=m["direction"] == "in")
    conn.commit()
    return "ok"


def record_business_event(conn, clients: dict, client_id: str, lead_id, event_type: str, occurred_at: datetime,
                          value=None, props=None, actor="staff", dedupe_key=None) -> None:
    """Bookings, show-ups, payments: from Cal.com/PayMongo webhooks or a staff button."""
    add_event(conn, client_id, lead_id, event_type, occurred_at, actor=actor, value=value, props=props,
              dedupe_key=dedupe_key)
    refresh_lead(conn, clients[client_id], lead_id, now=occurred_at)
    conn.commit()


def _stage_for(cfg: dict, reached: set[str]) -> str:
    stage = cfg["stages"][0]["key"]
    for s in cfg["stages"]:
        if reached.intersection(s["events"]):
            stage = s["key"]
    return stage


def _next_action(cfg: dict, lead: dict, now: datetime) -> tuple[str, int]:
    last = max([t for t in (lead["last_inbound_at"], lead["last_outbound_at"]) if t], default=now)
    idle_hours = (now - last).total_seconds() / 3600
    for rule in cfg["next_actions"]:
        w = rule["when"]
        if "awaiting_reply" in w and lead["awaiting_reply"] != w["awaiting_reply"]:
            continue
        if "temperature" in w and lead["temperature"] != w["temperature"]:
            continue
        if "stage" in w and lead["stage"] != w["stage"]:
            continue
        if "idle_hours" in w and idle_hours < w["idle_hours"]:
            continue
        return rule["action"], rule["priority"]
    return "No action needed", 5


def refresh_lead(conn, cfg: dict, lead_id, now: datetime, new_inbound: bool = False) -> dict:
    """Recompute everything derived for one lead. Safe to call any time (idempotent)."""
    msgs = conn.execute("SELECT direction, actor, sent_at, body FROM messages WHERE lead_id=%s AND sent_at <= %s ORDER BY sent_at",
                        (lead_id, now)).fetchall()
    lead = conn.execute("SELECT * FROM leads WHERE lead_id=%s", (lead_id,)).fetchone()
    client_id = lead["client_id"]

    last_in = max((x["sent_at"] for x in msgs if x["direction"] == "in"), default=None)
    last_out = max((x["sent_at"] for x in msgs if x["direction"] == "out"), default=None)
    awaiting = last_in is not None and (last_out is None or last_in > last_out)
    waiting_since = min((x["sent_at"] for x in msgs if x["direction"] == "in" and (last_out is None or x["sent_at"] > last_out)),
                        default=None) if awaiting else None

    reached = {r["event_type"] for r in conn.execute(
        "SELECT DISTINCT event_type FROM events WHERE lead_id=%s AND occurred_at <= %s", (lead_id, now)).fetchall()}
    committed = bool(reached & {"consult_booked", "appointment_showed", "payment_received", "contract_signed"})

    inbound_texts = [x["body"] or "" for x in msgs if x["direction"] == "in"]
    # Booked/paid customers don't "cool down" from silence; decay only applies to open leads.
    label = rule_classify(cfg, inbound_texts, None if committed else last_in, now)
    if new_inbound and label["ambiguous"]:
        llm = llm_classify(cfg, [("customer" if x["direction"] == "in" else x["actor"], x["body"] or "") for x in msgs])
        if llm:
            label.update({k: llm[k] for k in ("temperature", "intent", "next_action") if llm.get(k)})
            label["interest"] = llm.get("interest") or label["interest"]
            label["method"] = "llm"

    if label["qualified"]:
        add_event(conn, client_id, lead_id, "lead_qualified", now, actor="system",
                  props={"interest": label["interest"], "signals": label["signals"]}, dedupe_key=f"qualified:{lead_id}")
    if lead["temperature"] != label["temperature"]:
        add_event(conn, client_id, lead_id, "temperature_changed", now, actor="system",
                  props={"from": lead["temperature"], "to": label["temperature"], "score": label["score"],
                         "signals": label["signals"]})
        conn.execute("INSERT INTO lead_labels (lead_id, labeled_at, method, temperature, score, payload) VALUES (%s,%s,%s,%s,%s,%s)",
                     (lead_id, now, label["method"], label["temperature"], label["score"], json.dumps(label)))

    reached = {r["event_type"] for r in conn.execute(
        "SELECT DISTINCT event_type FROM events WHERE lead_id=%s AND occurred_at <= %s", (lead_id, now)).fetchall()}
    stage = _stage_for(cfg, reached)
    interest = label["interest"] or lead["interest"]
    est_value = cfg.get("interests", {}).get(interest, {}).get("value") if interest else None

    lead.update({"awaiting_reply": awaiting, "waiting_since": waiting_since, "last_inbound_at": last_in,
                 "last_outbound_at": last_out, "temperature": label["temperature"], "stage": stage})
    action, priority = _next_action(cfg, lead, now)
    if "paid" in reached or "contract_signed" in reached:
        action, priority = "Won: schedule follow-up / rebook date", 4

    conn.execute(
        """UPDATE leads SET stage=%s, temperature=%s, score=%s, intent=%s, interest=%s, est_value=%s,
             next_action=%s, next_action_priority=%s, awaiting_reply=%s, waiting_since=%s,
             last_inbound_at=%s, last_outbound_at=%s, updated_at=%s WHERE lead_id=%s""",
        (stage, label["temperature"], label["score"], label["intent"], interest, est_value, action, priority,
         awaiting, waiting_since, last_in, last_out, now, lead_id),
    )
    return lead


def refresh_all(conn, clients: dict, now: datetime) -> None:
    """Re-evaluate every lead as of `now` (decay, idle follow-ups). Run hourly."""
    for row in conn.execute("SELECT lead_id, client_id FROM leads").fetchall():
        refresh_lead(conn, clients[row["client_id"]], row["lead_id"], now)
    conn.commit()


def lead_trace(conn, lead_id) -> list[dict]:
    """A lead's trace: messages + business events merged on one timeline,
    each with the time since the previous span (the 'latency' between steps)."""
    rows = conn.execute(
        """SELECT sent_at AS at, CASE WHEN direction='in' THEN 'customer_message' ELSE actor || '_reply' END AS kind,
                  actor, body AS detail, NULL::numeric AS value
             FROM messages WHERE lead_id=%(id)s
           UNION ALL
           SELECT occurred_at, event_type, actor, props::text, value FROM events WHERE lead_id=%(id)s
           ORDER BY 1, 2""", {"id": lead_id}).fetchall()
    prev = None
    for r in rows:
        r["since_prev_min"] = round((r["at"] - prev).total_seconds() / 60, 1) if prev else 0
        prev = r["at"]
    return rows
