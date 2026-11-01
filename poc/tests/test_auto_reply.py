"""Meta's automatic "away" message comes from the same inbox app id as human replies.
Per-client `ignore_replies` patterns keep it stored but out of the reply-time maths."""
from datetime import datetime, timezone

from app.pipeline import is_auto_reply

from .conftest import page_event, post

T0 = int(datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 10:00 Manila
MIN = 60_000
INBOX_APP = "263902037430900"          # Meta Business Suite inbox: same id for human and automatic replies
GUEST = "40110389905214604"            # the tester guest from the handoff
AWAY = ("Hi Alyssa, thanks for contacting us! We're currently away. "
        "We'll get back to you as soon as we can.")


def away_echo(ts_ms: int, mid: str = "m_away", text: str = AWAY) -> dict:
    """Echo of the automatic reply, shaped like the real Messenger webhook (is_echo + inbox app_id)."""
    return page_event(ts_ms, mid=mid, customer=GUEST, text=text, echo_app=INBOX_APP)


def test_away_reply_is_stored_but_does_not_close_the_wait(client, db):
    post(client, page_event(T0, mid="q1", customer=GUEST, text="Hi, available po this weekend?"))
    r = post(client, away_echo(T0 + 6_000))            # Meta answers 6 seconds later
    assert r.json()["results"] == {"ok": 1}

    msg = db.execute("SELECT direction, actor, body FROM messages WHERE message_id='m_away'").fetchone()
    assert (msg["direction"], msg["actor"]) == ("out", "auto_reply") and msg["body"] == AWAY

    pair = db.execute("SELECT replied_at, raw_minutes FROM v_reply_pairs").fetchone()
    assert pair["replied_at"] is None and pair["raw_minutes"] is None
    lead = db.execute("SELECT awaiting_reply, last_outbound_at FROM leads").fetchone()
    assert lead["awaiting_reply"] and lead["last_outbound_at"] is None
    assert db.execute("SELECT count(*) AS n FROM events WHERE event_type='first_reply'").fetchone()["n"] == 0


def test_human_reply_after_away_reply_gives_the_real_first_reply_time(client, db):
    post(client, page_event(T0, mid="q1", customer=GUEST, text="Hi, available po this weekend?"))
    post(client, away_echo(T0 + 6_000))
    post(client, page_event(T0 + 9 * MIN, mid="h1", customer=GUEST, text="Hello po! Yes, available.", echo_app=INBOX_APP))

    pair = db.execute("SELECT raw_minutes, replied_by, is_first_response FROM v_reply_pairs").fetchone()
    assert float(pair["raw_minutes"]) == 9.0 and pair["replied_by"] == "staff" and pair["is_first_response"]
    assert db.execute("SELECT count(*) AS n FROM events WHERE event_type='first_reply'").fetchone()["n"] == 1
    assert db.execute("SELECT awaiting_reply FROM leads").fetchone()["awaiting_reply"] is False
    kpi = db.execute("SELECT frt_p50_min FROM v_daily_kpis").fetchone()
    assert float(kpi["frt_p50_min"]) == 9.0


def test_away_reply_does_not_split_a_block_of_customer_messages(client, db):
    post(client, page_event(T0, mid="q1", customer=GUEST, text="hello"))
    post(client, away_echo(T0 + 1_000))
    post(client, page_event(T0 + 2 * MIN, mid="q2", customer=GUEST, text="anyone there?"))
    post(client, page_event(T0 + 10 * MIN, mid="h1", customer=GUEST, text="Hi!", echo_app=INBOX_APP))
    rows = db.execute("SELECT raw_minutes, msgs_in_block FROM v_reply_pairs").fetchall()
    assert len(rows) == 1 and float(rows[0]["raw_minutes"]) == 10.0 and rows[0]["msgs_in_block"] == 2


def test_ordinary_staff_reply_still_counts(client, db):
    post(client, page_event(T0, mid="q1", customer=GUEST, text="hello"))
    post(client, page_event(T0 + 3 * MIN, mid="h1", customer=GUEST, text="We're open today, how can we help?", echo_app=INBOX_APP))
    assert db.execute("SELECT actor FROM messages WHERE direction='out'").fetchone()["actor"] == "staff"
    assert float(db.execute("SELECT raw_minutes FROM v_reply_pairs").fetchone()["raw_minutes"]) == 3.0


def test_trace_labels_the_away_reply(client, db):
    from app.pipeline import lead_trace
    post(client, page_event(T0, mid="q1", customer=GUEST, text="hello"))
    post(client, away_echo(T0 + 1_000))
    lead_id = db.execute("SELECT lead_id FROM leads").fetchone()["lead_id"]
    assert "auto_reply" in [r["kind"] for r in lead_trace(db, lead_id)]


def test_is_auto_reply_matching():
    cfg = {"client_id": "x", "ignore_replies": ["thanks for contacting us.{0,20}we.re currently away", "[unclosed"]}
    assert is_auto_reply(cfg, AWAY)
    assert is_auto_reply(cfg, AWAY.replace("'", "’").upper())          # curly apostrophe, any case
    assert not is_auto_reply(cfg, "Hi! Yes, we're available this weekend.")
    assert not is_auto_reply(cfg, "")
    assert not is_auto_reply({"client_id": "x"}, AWAY)                      # no rule configured: nothing ignored
