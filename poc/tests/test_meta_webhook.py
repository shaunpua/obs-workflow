from datetime import datetime, timezone

from .conftest import page_event, post

T0 = int(datetime(2026, 10, 5, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 10:00 Manila
MIN = 60_000


def test_verify_handshake(client):
    ok = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "test-verify", "hub.challenge": "12345"})
    assert ok.status_code == 200 and ok.text == "12345"
    bad = client.get("/webhooks/meta", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
    assert bad.status_code == 403


def test_bad_signature_is_rejected(client, db):
    r = client.post("/webhooks/meta", content=b"{}", headers={"X-Hub-Signature-256": "sha256=deadbeef"})
    assert r.status_code == 403
    assert db.execute("SELECT count(*) AS n FROM raw_webhooks").fetchone()["n"] == 0


def test_inbound_then_staff_echo_gives_reply_time(client, db):
    assert post(client, page_event(T0, mid="m1", text="Hi, available po ba this weekend? 4 pax kami")).status_code == 200
    r = post(client, page_event(T0 + 7 * MIN, mid="m2", text="Hello! Yes po, available.", echo_app="263902037430900"))
    assert r.json()["results"] == {"ok": 1}

    msgs = db.execute("SELECT direction, actor FROM messages ORDER BY sent_at").fetchall()
    assert [(m["direction"], m["actor"]) for m in msgs] == [("in", "customer"), ("out", "staff")]

    pair = db.execute("SELECT raw_minutes, replied_by, is_first_response FROM v_reply_pairs").fetchone()
    assert float(pair["raw_minutes"]) == 7.0 and pair["replied_by"] == "staff" and pair["is_first_response"]


def test_ai_app_id_is_labelled_ai(client, db):
    post(client, page_event(T0, mid="a1", text="magkano po?"))
    post(client, page_event(T0 + MIN, mid="a2", text="Hi! 4,500 per night.", echo_app="APP_AI_1"))
    assert db.execute("SELECT actor FROM messages WHERE direction='out'").fetchone()["actor"] == "ai"


def test_duplicate_delivery_is_ignored(client, db):
    payload = page_event(T0, mid="dup1", text="hello")
    assert post(client, payload).json()["results"] == {"ok": 1}
    assert post(client, payload).json()["results"] == {"duplicate": 1}
    assert db.execute("SELECT count(*) AS n FROM messages").fetchone()["n"] == 1


def test_three_messages_in_a_row_count_as_one_wait(client, db):
    for i, dt in enumerate((0, 1, 2)):
        post(client, page_event(T0 + dt * MIN, mid=f"b{i}", text="hello"))
    post(client, page_event(T0 + 10 * MIN, mid="b9", text="Hi!", echo_app="999"))
    rows = db.execute("SELECT raw_minutes, msgs_in_block FROM v_reply_pairs").fetchall()
    assert len(rows) == 1 and float(rows[0]["raw_minutes"]) == 10.0 and rows[0]["msgs_in_block"] == 3


def test_ad_referral_is_captured_on_lead(client, db):
    post(client, page_event(T0, mid="r1", text="Hi", referral={"source": "ADS", "type": "OPEN_THREAD", "ad_id": "AD_123"}))
    lead = db.execute("SELECT first_source, first_ad_id FROM leads").fetchone()
    assert lead["first_source"] == "ad" and lead["first_ad_id"] == "AD_123"


def test_unknown_page_is_stored_but_not_processed(client, db):
    r = post(client, page_event(T0, mid="u1", page="SOME_OTHER_PAGE"))
    assert r.status_code == 200 and r.json()["results"] == {"unknown_channel": 1}
    assert db.execute("SELECT count(*) AS n FROM raw_webhooks").fetchone()["n"] == 1
    assert db.execute("SELECT count(*) AS n FROM messages").fetchone()["n"] == 0


def test_hot_label_for_booking_intent(client, db):
    post(client, page_event(T0, mid="h1", text="Hi! Available po ba this weekend? 4 pax kami, pa-book na po"))
    lead = db.execute("SELECT temperature, intent, awaiting_reply FROM leads").fetchone()
    assert lead["temperature"] == "hot" and lead["intent"] == "ready_to_book" and lead["awaiting_reply"]


def test_name_lookup_fills_display_name(client, db, monkeypatch):
    from app import profiles
    monkeypatch.setenv("META_PAGE_TOKEN", "tok")
    monkeypatch.setattr(profiles, "fetch_profile", lambda psid, token: {"first_name": "Ana", "last_name": "Reyes"})
    post(client, page_event(T0, mid="n1", text="hello"))   # the webhook's background task fills the name
    assert db.execute("SELECT display_name FROM leads").fetchone()["display_name"] == "Ana Reyes"
