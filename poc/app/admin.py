"""Plain admin pages: logs, metrics, traces. No JS, no styling beyond the basics.

Open  http://localhost:8765/admin?key=<API_KEY from .env>
(The tunnel exposes the whole app, so every page needs the key.)
"""
from __future__ import annotations

import collections
import html
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import pipeline

# Last 300 app log lines, kept in memory (lost on restart; the durable record is the raw_webhooks table).
_LOG_LINES: collections.deque[str] = collections.deque(maxlen=300)


class _Ring(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _LOG_LINES.append(self.format(record))


def install_log_ring() -> None:
    h = _Ring()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(h)


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def page(title: str, key: str, body: str) -> HTMLResponse:
    nav = " | ".join(f'<a href="/admin{p}?key={e(key)}">{n}</a>' for p, n in
                     [("", "Metrics"), ("/logs", "Logs"), ("/leads", "Leads")])
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(title)}</title>
<style>body{{font:14px monospace;margin:16px}}table{{border-collapse:collapse}}td,th{{border:1px solid #999;padding:2px 6px;text-align:left;vertical-align:top}}
.bad{{color:#b00}}pre{{white-space:pre-wrap}}</style></head><body><p>{nav}</p><h2>{e(title)}</h2>{body}</body></html>""")


def table(headers: list[str], rows: list[list], bad_col: int | None = None) -> str:
    out = ["<table><tr>" + "".join(f"<th>{e(h)}</th>" for h in headers) + "</tr>"]
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            cls = ' class="bad"' if bad_col == i and c else ""
            cells.append(f"<td{cls}>{e(c)}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out.append("</table>")
    return "".join(out) if rows else "<p>(nothing yet)</p>"


def make_router(conn, api_key: str) -> APIRouter:
    r = APIRouter(prefix="/admin")

    def auth(key: str | None) -> str:
        if key != api_key:
            raise HTTPException(401, "add ?key=<API_KEY from poc/.env>")
        return key

    def q(sql: str, params=()):
        try:
            return conn.execute(sql, params).fetchall()
        except Exception:
            conn.rollback()
            raise

    @r.get("", response_class=HTMLResponse)
    def metrics(key: str | None = Query(None)):
        auth(key)
        h = q("""SELECT count(*) AS total,
                        count(*) FILTER (WHERE error IS NOT NULL) AS errors,
                        count(*) FILTER (WHERE processed_at IS NULL AND error IS NULL) AS pending,
                        max(received_at) AS last_at, round(extract(epoch FROM now()-max(received_at))/60) AS last_min
                   FROM raw_webhooks""")[0]
        msgs = q("SELECT direction, count(*) AS n FROM messages GROUP BY 1")
        mc = {m["direction"]: m["n"] for m in msgs}
        body = "<h3>Health</h3>" + table(
            ["webhooks received", "failed to process", "unprocessed", "last webhook", "minutes ago"],
            [[h["total"], h["errors"], h["pending"], h["last_at"], h["last_min"]]], bad_col=1)
        body += table(["messages in (customer)", "messages out (staff/AI)"], [[mc.get("in", 0), mc.get("out", 0)]])
        body += "<h3>Reply time (business-hours aware), by day</h3>" + table(
            ["client", "day", "conversations", "never answered", "p50 raw min", "p90 raw min", "p50 business min", "by AI", "after hours"],
            [[k["client_id"], k["day"], k["new_conversations"], k["never_answered"],
              _r(k["frt_p50_min"]), _r(k["frt_p90_min"]), _r(k["frt_p50_business_min"]), k["answered_by_ai"], k["after_hours"]]
             for k in q("SELECT * FROM v_daily_kpis ORDER BY day DESC, client_id LIMIT 30")])
        body += "<h3>Leads now</h3>" + table(["client", "temperature", "stage", "count", "waiting for a reply"], [
            [k["client_id"], k["temperature"], k["stage"], k["n"], k["waiting"]] for k in q(
                """SELECT client_id, temperature, stage, count(*) AS n, count(*) FILTER (WHERE awaiting_reply) AS waiting
                     FROM leads GROUP BY 1,2,3 ORDER BY 1,2,3""")])
        body += "<h3>Open alerts</h3>" + table(["fired", "client", "type", "message"], [
            [k["fired_at"], k["client_id"], k["alert_type"], k["message"]] for k in q(
                "SELECT * FROM alerts WHERE resolved_at IS NULL ORDER BY fired_at DESC LIMIT 20")])
        return page("Metrics", key, body)

    @r.get("/logs", response_class=HTMLResponse)
    def logs(key: str | None = Query(None), n: int = 50):
        auth(key)
        raws = q("""SELECT id, received_at, source, signature_ok, processed_at IS NOT NULL AS done, error,
                           left(payload::text, 160) AS payload FROM raw_webhooks ORDER BY id DESC LIMIT %s""", (n,))
        body = "<h3>Webhooks received (newest first)</h3>" + table(
            ["id", "received", "source", "signed ok", "processed", "error", "payload (start)"],
            [[x["id"], x["received_at"], x["source"], x["signature_ok"], x["done"], x["error"], x["payload"]] for x in raws], bad_col=5)
        msgs = q("""SELECT m.sent_at, m.client_id, COALESCE(l.display_name, l.external_user_id) AS who, m.direction, m.actor,
                           left(m.body, 100) AS body, m.lead_id FROM messages m JOIN leads l USING (lead_id)
                     ORDER BY m.sent_at DESC LIMIT %s""", (n,))
        body += "<h3>Messages</h3>" + table(["sent", "client", "who", "dir", "actor", "text", "lead"],
                                            [[m["sent_at"], m["client_id"], m["who"], m["direction"], m["actor"], m["body"], str(m["lead_id"])[:8]] for m in msgs])
        body += "<h3>App log (last 300 lines, this run only)</h3><pre>" + e("\n".join(reversed(_LOG_LINES))) + "</pre>"
        return page("Logs", key, body)

    @r.get("/leads", response_class=HTMLResponse)
    def leads(key: str | None = Query(None)):
        auth(key)
        rows = q("""SELECT lead_id, client_id, COALESCE(display_name, external_user_id) AS who, channel, stage, temperature,
                           score, intent, awaiting_reply, waiting_since, next_action FROM leads ORDER BY updated_at DESC LIMIT 100""")
        body = "<table><tr>" + "".join(f"<th>{h}</th>" for h in
                ["who", "client", "channel", "stage", "temp", "score", "intent", "waiting since", "next action", "trace"]) + "</tr>"
        for x in rows:
            body += ("<tr>" + "".join(f"<td>{e(v)}</td>" for v in [x["who"], x["client_id"], x["channel"], x["stage"], x["temperature"],
                                                                    x["score"], x["intent"], x["waiting_since"] if x["awaiting_reply"] else "", x["next_action"]])
                     + f'<td><a href="/admin/trace/{x["lead_id"]}?key={e(key)}">trace</a></td></tr>')
        body += "</table>" if rows else "</table><p>(nothing yet)</p>"
        return page("Leads", key, body)

    @r.get("/trace/{lead_id}", response_class=HTMLResponse)
    def trace(lead_id: str, key: str | None = Query(None)):
        auth(key)
        rows = pipeline.lead_trace(conn, lead_id)
        body = table(["time", "step", "actor", "minutes since previous", "value", "detail"],
                     [[x["at"], x["kind"], x["actor"], x["since_prev_min"], x["value"], x["detail"]] for x in rows])
        labels = q("SELECT labeled_at, method, temperature, score, payload::text AS p FROM lead_labels WHERE lead_id=%s ORDER BY labeled_at", (lead_id,))
        body += "<h3>Classification history</h3>" + table(["when", "method", "temp", "score", "why"],
                                                          [[x["labeled_at"], x["method"], x["temperature"], x["score"], x["p"]] for x in labels])
        return page("Trace " + lead_id[:8], key, body)

    return r


def _r(v):
    return None if v is None else round(float(v), 1)
