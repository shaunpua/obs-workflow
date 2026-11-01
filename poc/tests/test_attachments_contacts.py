"""Attachments / shared links are stored as references; phone and email typed by the guest land on the lead."""
import pytest

from app.contacts import extract_emails, extract_phones, extract_urls

from .conftest import page_event, post
from .test_auto_reply import GUEST, INBOX_APP, MIN, T0


def with_attachments(payload: dict, attachments: list, text: str | None = None) -> dict:
    msg = payload["entry"][0]["messaging"][0]["message"]
    msg["attachments"] = attachments
    if text is None:
        msg.pop("text", None)
    return payload


def test_image_attachment_is_stored_as_reference(client, db):
    img = {"type": "image", "payload": {"url": "https://scontent.xx.fbcdn.net/v/t1/photo.jpg?oh=abc&oe=123"}}
    post(client, with_attachments(page_event(T0, mid="a1", customer=GUEST), [img]))
    row = db.execute("SELECT body, attachments FROM messages").fetchone()
    assert row["attachments"] == [{"type": "image", "url": img["payload"]["url"], "title": None}]
    assert not row["body"]


def test_shared_link_fallback_attachment_is_stored_as_link(client, db):
    fb = {"type": "fallback", "title": "BackHome BGC | Airbnb", "url": "https://l.facebook.com/l.php?u=https%3A%2F%2Fairbnb.com%2Frooms%2F1",
          "payload": None}
    post(client, with_attachments(page_event(T0, mid="a2", customer=GUEST), [fb], text="is this you?"))
    att = db.execute("SELECT attachments FROM messages").fetchone()["attachments"]
    assert att == [{"type": "link", "url": fb["url"], "title": "BackHome BGC | Airbnb"}]


def test_location_sticker_and_file_attachments(client, db):
    atts = [{"type": "location", "title": "Pin", "payload": {"coordinates": {"lat": 14.55, "long": 121.05}, "url": "https://maps/x"}},
            {"type": "image", "payload": {"url": "https://cdn/s.png", "sticker_id": 369239263222822}},
            {"type": "file", "payload": {"url": "https://cdn/id.pdf"}}]
    post(client, with_attachments(page_event(T0, mid="a3", customer=GUEST), atts))
    got = db.execute("SELECT attachments FROM messages").fetchone()["attachments"]
    assert [a["type"] for a in got] == ["location", "sticker", "file"]
    assert (got[0]["lat"], got[0]["long"]) == (14.55, 121.05)


def test_url_typed_in_text_is_kept_once(client, db):
    post(client, page_event(T0, mid="a4", customer=GUEST, text="saw this https://airbnb.com/rooms/1, same place?"))
    att = db.execute("SELECT attachments FROM messages").fetchone()["attachments"]
    assert att == [{"type": "link", "url": "https://airbnb.com/rooms/1", "title": None, "from_text": True}]


def test_plain_message_has_no_attachments(client, db):
    post(client, page_event(T0, mid="a5", customer=GUEST, text="hello"))
    assert db.execute("SELECT attachments FROM messages").fetchone()["attachments"] == []


def test_phone_and_email_from_guest_text_land_on_lead(client, db):
    post(client, page_event(T0, mid="c1", customer=GUEST, text="Hi! Pa-book po. Contact me 0917 123 4567 or Ana.Reyes@Gmail.com"))
    lead = db.execute("SELECT phone, email FROM leads").fetchone()
    assert (lead["phone"], lead["email"]) == ("09171234567", "ana.reyes@gmail.com")
    kinds = {r["event_type"] for r in db.execute("SELECT event_type FROM events")}
    assert {"phone_captured", "email_captured"} <= kinds
    props = " ".join(r["props"] if isinstance(r["props"], str) else str(r["props"]) for r in db.execute("SELECT props FROM events"))
    assert "09171234567" not in props and "gmail" not in props      # no contact data copied into trace props


def test_first_contact_wins_and_later_messages_do_not_overwrite(client, db):
    post(client, page_event(T0, mid="c2", customer=GUEST, text="call +63 917 123 4567"))
    post(client, page_event(T0 + MIN, mid="c3", customer=GUEST, text="or 0998-765-4321"))
    assert db.execute("SELECT phone FROM leads").fetchone()["phone"] == "+639171234567"


def test_staff_message_with_a_phone_number_is_not_mined(client, db):
    post(client, page_event(T0, mid="c4", customer=GUEST, text="hello"))
    post(client, page_event(T0 + MIN, mid="c5", customer=GUEST, text="Call us 0917 000 1111 / hello@backhome.ph", echo_app=INBOX_APP))
    lead = db.execute("SELECT phone, email FROM leads").fetchone()
    assert lead["phone"] is None and lead["email"] is None


def test_dates_and_prices_are_not_phone_numbers(client, db):
    post(client, page_event(T0, mid="c6", customer=GUEST, text="Oct 18-19, 4 pax, budget 1,500,000 or 2026-10-05, 4500/night"))
    assert db.execute("SELECT phone FROM leads").fetchone()["phone"] is None


def test_migrate_can_run_twice(db):
    from app.db import migrate
    migrate(db)      # the start-up migration re-runs 001 on an existing DB: the ALTERs must be idempotent
    migrate(db)


@pytest.mark.parametrize("text,phones", [
    ("0917 123 4567", ["09171234567"]),
    ("+63 917-123-4567", ["+639171234567"]),
    ("(02) 8123 4567", ["0281234567"]),
    ("tawag 09171234567.", ["09171234567"]),
    ("12345", []), ("Oct 18-19 2026", []), ("1,500,000", []), ("2026-10-05", []),
    ("ana.1234567890@gmail.com", []),                      # digits inside an email
    ("0917 123 4567 / 0998 765 4321", ["09171234567", "09987654321"]),
])
def test_extract_phones(text, phones):
    assert extract_phones(text) == phones


def test_extract_emails_and_urls():
    assert extract_emails("mail Ana@Example.com, or ana@example.com.") == ["ana@example.com"]
    assert extract_emails("no email here @home") == []
    assert extract_urls("see (https://a.com/x?y=1), and http://b.org.") == ["https://a.com/x?y=1", "http://b.org"]
