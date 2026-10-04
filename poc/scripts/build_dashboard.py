"""Build the customer-facing dashboard (one self-contained HTML file) from Postgres.

    python -m scripts.build_dashboard --client demo-clinic --out out/dashboard.html

This is the "custom portal" option in its simplest form: SQL views -> JSON -> HTML.
The same views can be pointed at Metabase or Grafana instead.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.config import load_all_clients
from app.db import connect
from app.pipeline import lead_trace, refresh_all

ROOT = Path(__file__).resolve().parent.parent
MERMAID = '<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>' \
          '<script>mermaid.initialize({startOnLoad:true,theme:"neutral"});</script>'


def _default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def q(conn, sql, **params):
    return conn.execute(sql, params).fetchall()


def build(conn, client_id: str, cfg: dict) -> dict:
    tz = cfg.get("timezone", "Asia/Manila")
    first_day = q(conn, "SELECT min(day) AS d FROM v_daily_kpis WHERE client_id=%(c)s", c=client_id)[0]["d"]
    ai_day = q(conn, """SELECT min((asked_at AT TIME ZONE %(tz)s)::date) AS d FROM v_reply_pairs
                        WHERE client_id=%(c)s AND replied_by='ai'""", c=client_id, tz=tz)[0]["d"]

    periods = q(conn, f"""
        WITH per_lead AS (
          SELECT l.lead_id,
                 CASE WHEN %(ai)s::date IS NOT NULL AND (l.created_at AT TIME ZONE '{tz}')::date >= %(ai)s
                      THEN 'after' ELSE 'before' END AS period,
                 fr.replied_at, fr.raw_minutes, fr.asked_in_hours,
                 EXISTS (SELECT 1 FROM events e WHERE e.lead_id=l.lead_id AND e.event_type='consult_booked') AS booked,
                 (SELECT SUM(value) FROM events e WHERE e.lead_id=l.lead_id AND e.event_type='payment_received') AS revenue
            FROM leads l
            LEFT JOIN v_reply_pairs fr ON fr.lead_id=l.lead_id AND fr.is_first_response
           WHERE l.client_id=%(c)s)
        SELECT period, COUNT(*) AS leads,
               ROUND(100.0 * COUNT(replied_at) / COUNT(*), 0) AS answered_pct,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_minutes) AS frt_p50,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY raw_minutes) AS frt_p90,
               ROUND(100.0 * COUNT(*) FILTER (WHERE NOT asked_in_hours) / COUNT(*), 0) AS after_hours_pct,
               COUNT(*) FILTER (WHERE booked) AS booked,
               COALESCE(SUM(revenue), 0) AS revenue
          FROM per_lead GROUP BY 1""", c=client_id, ai=ai_day)

    daily = q(conn, """SELECT day, new_conversations AS leads, never_answered, frt_p50_min AS p50, frt_p90_min AS p90,
                              answered_by_ai AS ai, after_hours FROM v_daily_kpis WHERE client_id=%(c)s ORDER BY day""", c=client_id)

    by_hour = q(conn, f"""SELECT EXTRACT(HOUR FROM asked_at AT TIME ZONE '{tz}')::int AS hour, COUNT(*) AS leads,
                                 COUNT(*) FILTER (WHERE replied_at IS NULL) AS unanswered,
                                 percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_minutes) AS p50
                            FROM v_reply_pairs WHERE client_id=%(c)s AND is_first_response GROUP BY 1 ORDER BY 1""", c=client_id)

    # Funnel: how many leads reached each stage, and how long the step into it took.
    funnel = []
    prev_events = None
    for s in cfg["stages"]:
        later = [x for st in cfg["stages"][cfg["stages"].index(s):] for x in st["events"]]
        row = q(conn, """SELECT COUNT(DISTINCT lead_id) AS n FROM events
                          WHERE client_id=%(c)s AND event_type = ANY(%(ev)s)""", c=client_id, ev=later)[0]
        step = None
        if prev_events:
            step = q(conn, """SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY h) AS p50,
                                     percentile_cont(0.9) WITHIN GROUP (ORDER BY h) AS p90 FROM (
                                SELECT GREATEST(0, EXTRACT(EPOCH FROM (b.reached_at - a.reached_at))/3600) AS h
                                  FROM (SELECT lead_id, MIN(reached_at) reached_at FROM v_lead_milestones
                                         WHERE client_id=%(c)s AND event_type = ANY(%(pe)s) GROUP BY 1) a
                                  JOIN (SELECT lead_id, MIN(reached_at) reached_at FROM v_lead_milestones
                                         WHERE client_id=%(c)s AND event_type = ANY(%(ev)s) GROUP BY 1) b USING (lead_id)) x""",
                     c=client_id, pe=prev_events, ev=s["events"])[0]
        funnel.append({"key": s["key"], "label": s["label"], "n": row["n"], "step_hours": step})
        prev_events = s["events"]

    sources = q(conn, """SELECT COALESCE(l.first_ad_id, 'Organic / no ad') AS source, COUNT(*) AS leads,
                                COUNT(*) FILTER (WHERE EXISTS (SELECT 1 FROM events e WHERE e.lead_id=l.lead_id AND e.event_type='consult_booked')) AS booked,
                                COALESCE(SUM((SELECT SUM(value) FROM events e WHERE e.lead_id=l.lead_id AND e.event_type='payment_received')),0) AS revenue
                           FROM leads l WHERE client_id=%(c)s GROUP BY 1 ORDER BY revenue DESC, leads DESC""", c=client_id)

    temps = q(conn, "SELECT temperature, COUNT(*) AS n FROM leads WHERE client_id=%(c)s GROUP BY 1", c=client_id)

    queue = q(conn, """SELECT lead_id, display_name, channel, stage, temperature, score, intent, interest, est_value,
                              next_action, next_action_priority AS priority, awaiting_reply, waiting_since,
                              COALESCE(last_inbound_at, created_at) AS last_seen
                         FROM leads WHERE client_id=%(c)s AND next_action_priority <= 3
                        ORDER BY next_action_priority, temperature='hot' DESC, est_value DESC NULLS LAST, last_seen DESC
                        LIMIT 14""", c=client_id)

    replies = q(conn, """SELECT replied_by, COUNT(*) AS n, percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_minutes) AS p50
                           FROM v_reply_pairs WHERE client_id=%(c)s AND replied_at IS NOT NULL GROUP BY 1""", c=client_id)

    alerts = q(conn, """SELECT a.alert_type, a.fired_at, a.resolved_at, a.message, l.display_name
                          FROM alerts a JOIN leads l USING (lead_id) WHERE a.client_id=%(c)s
                         ORDER BY a.fired_at DESC LIMIT 8""", c=client_id)

    # Three example traces: a paid customer, a lead lost to a slow night reply, an AI-handled lead.
    picks = {
        "Paid customer": "EXISTS (SELECT 1 FROM events e WHERE e.lead_id=l.lead_id AND e.event_type='payment_received')",
        "Lost overnight": """l.temperature='cold' AND EXISTS (SELECT 1 FROM v_reply_pairs p WHERE p.lead_id=l.lead_id
                              AND p.is_first_response AND p.raw_minutes > 600)""",
        "Answered by AI at night": "EXISTS (SELECT 1 FROM v_reply_pairs p WHERE p.lead_id=l.lead_id AND p.is_first_response AND p.replied_by='ai') AND l.temperature='hot'",
    }
    traces = []
    for title, where in picks.items():
        row = q(conn, f"""SELECT lead_id, display_name, channel, interest, temperature, stage FROM leads l
                           WHERE client_id=%(c)s AND {where} ORDER BY created_at LIMIT 1""", c=client_id)
        if row:
            traces.append({"title": title, "lead": row[0], "spans": lead_trace(conn, row[0]["lead_id"])})

    return {"client": {"id": client_id, "name": cfg["name"], "niche": cfg["niche"], "timezone": tz,
                       "hours": cfg.get("business_hours", {}), "sla": cfg["sla"]},
            "generated_at": datetime.now(timezone.utc), "first_day": first_day, "ai_day": ai_day,
            "periods": {p["period"]: p for p in periods}, "daily": daily, "by_hour": by_hour,
            "funnel": funnel, "sources": sources, "temperatures": temps, "queue": queue,
            "replies": replies, "alerts": alerts, "traces": traces}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", default="demo-clinic")
    ap.add_argument("--out", default=str(ROOT / "out" / "dashboard.html"))
    ap.add_argument("--standalone", action="store_true", help="load mermaid from cdnjs so diagrams render when opened from disk")
    args = ap.parse_args()

    clients = load_all_clients()
    with connect() as conn:
        refresh_all(conn, clients, datetime.now(timezone.utc))
        data = build(conn, args.client, clients[args.client])

    html = (ROOT / "dashboard" / "template.html").read_text()
    html = html.replace("/*__DATA__*/null", json.dumps(data, default=_default))
    html = html.replace("<!--__MERMAID__-->", MERMAID if args.standalone else "")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    (out.parent / "dashboard-data.json").write_text(json.dumps(data, default=_default, indent=1))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
