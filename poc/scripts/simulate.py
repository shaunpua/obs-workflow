"""Replay 14 days of realistic clinic conversations through the real webhook endpoint.

Generates Meta-shaped webhook payloads (Messenger, Instagram, WhatsApp), signs them
with the app secret exactly like Meta does, and POSTs them in time order. Also posts
bookings/show-ups/payments and runs the alert check every 5 simulated minutes.

The story baked into the data:
- Most inquiries arrive in the evening, after the clinic closes at 20:00.
- Days 1-7 (baseline): only staff reply. Night messages wait until morning; some never get answered.
- Days 8-14: the AI responder answers after hours within a minute.
- The slower the reply, the more likely the customer disappears.

Usage:
    python -m scripts.simulate                 # in-process (no server needed)
    python -m scripts.simulate --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Manila")
APP_SECRET = os.environ.get("META_APP_SECRET", "dev-secret")
API_KEY = os.environ.get("API_KEY", "dev-api-key")
PAGE, IG, WA = "PAGE_GLOW_001", "IG_GLOW_001", "WA_PNID_GLOW_001"
AI_APP, INBOX_APP = "APP_REVOBS_AI", "263902037430900"   # 2nd = Meta Business Suite inbox
OPEN_H, CLOSE_H = 9, 20

NAMES = ["Andrea", "Bea", "Carla", "Dianne", "Ella", "Faith", "Gela", "Hazel", "Ivy", "Jen", "Kat", "Lianne",
         "Mae", "Nikki", "Olive", "Pia", "Queenie", "Rica", "Sam", "Tin", "Uma", "Vina", "Wendy", "Yna", "Zoe",
         "Aly", "Bianca", "Cha", "Denise", "Erika", "Joy", "Kim", "Lara", "Mika", "Nina", "Pat", "Rose", "Sheena",
         "Trish", "Vic", "Aira", "Belle", "Cams", "Dani", "Eunice", "Fritz", "Gab", "Hannah", "Isay", "Jas"]
ADS = {"botox": "AD_BOTOX_OCT", "laser": "AD_LASER_VIDEO", "skin_booster": "AD_SKINBOOSTER_PROMO", "filler": "AD_FILLER_CAROUSEL"}

# Each scenario: customer lines (each is a "turn"; a turn may hold several quick messages),
# the business reply to each turn, and what happens if the customer reaches the end.
SCENARIOS = {
    "hot_booker": dict(weight=22, interest="botox", outcome="book", turns=[
        (["Hi! Magkano po botox?"], "Hi po! Botox starts at P12,000 for 50 units. May I know which area po?"),
        (["Jaw slim po sana. Available po ba kayo bukas ng hapon? Pa-book po sana"], "Yes po! We have 2pm or 4pm tomorrow. Which one po?"),
        (["4pm po. Saan po location niyo?"], "Booked po for 4pm! We're at 2F Glow Bldg, Kapitolyo, Pasig. See you!"),
    ]),
    "budget_hot": dict(weight=12, interest="skin_booster", outcome="book", turns=[
        (["Hi po, may promo po kayo for skin booster?", "Budget ko around 15k, pwede gcash?"], "Hi po! Rejuran is P16,000, this month P14,500 promo. GCash accepted po."),
        (["Pwede po ba this Saturday?"], "Saturday 11am or 3pm available po."),
        (["11am po please"], "Confirmed po! Saturday 11am. Reminder will be sent a day before."),
    ]),
    "warm_comparer": dict(weight=18, interest="laser", outcome="think", turns=[
        (["Hello, how much po laser for melasma?", "Ilang sessions po usually?"], "Hi po! Pico laser is P8,000/session, usually 4-6 sessions."),
        (["Masakit po ba? May downtime?"], "Mild sting lang po, no downtime. Want me to check available slots?"),
        (["Sige po pag-iisipan ko muna, thank you"], "Sure po! Message us anytime."),
    ]),
    "price_shopper": dict(weight=20, interest="filler", outcome="none", turns=[
        (["hm po filler"], "Hi po! Lip filler starts at P25,000 per syringe. Which area po?"),
        (["ok po thanks"], "Welcome po!"),
    ]),
    "too_expensive": dict(weight=10, interest="facial", outcome="none", turns=[
        (["magkano po facial"], "Hydrafacial is P3,500 po."),
        (["mahal pala, wag na po"], "No worries po, we also have a basic facial at P1,200."),
    ]),
    "burst_then_book": dict(weight=10, interest="slimming", outcome="book_noshow", turns=[
        (["Hi", "Ask ko lang po", "Magkano po slimming? Yung sa tummy"], "Hi po! Body contouring is P30,000 for 6 sessions."),
        (["May available po ba sa weekend? Saturday sana"], "Saturday 1pm po available."),
        (["Sige po book ko na"], "Done po! See you Saturday 1pm."),
    ]),
    "wa_returning": dict(weight=8, interest="botox", outcome="book", channel="whatsapp", turns=[
        (["Good evening po, follow up ko lang yung botox, avail pa po ba sa Monday? Pa-book na po"], "Hi po! Monday 10am or 5pm open po."),
        (["5pm po, thank you!"], "Booked po Monday 5pm!"),
    ]),
}

# Inquiry arrival by hour of day (Manila). People message after work.
HOUR_WEIGHTS = [2, 1, 1, 0, 0, 0, 1, 2, 3, 4, 4, 5, 7, 6, 4, 4, 4, 5, 6, 8, 10, 11, 10, 6]


def in_hours(t: datetime) -> bool:
    lt = t.astimezone(TZ)
    return lt.isoweekday() <= 6 and OPEN_H <= lt.hour < CLOSE_H


def next_open(t: datetime) -> datetime:
    lt = t.astimezone(TZ)
    candidate = lt.replace(hour=OPEN_H, minute=0, second=0, microsecond=0)
    if lt >= candidate:
        candidate += timedelta(days=1)
    while candidate.isoweekday() == 7:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def business_reply(rng: random.Random, asked: datetime, ai_on: bool, busy: float) -> tuple[datetime, str] | None:
    """When (and who) replies to a customer message, or None if nobody ever does."""
    if in_hours(asked):
        if rng.random() < 0.06:
            return None
        return asked + timedelta(minutes=rng.lognormvariate(2.6 + busy, 0.8)), "staff"
    if ai_on:
        return asked + timedelta(seconds=rng.randint(20, 75)), "ai"
    if rng.random() < 0.22:
        return None                                   # lost in the inbox overnight
    return next_open(asked) + timedelta(minutes=rng.lognormvariate(3.3, 0.7)), "staff"


def p_continue(delay: timedelta) -> float:
    m = delay.total_seconds() / 60
    return 0.92 if m < 15 else 0.72 if m < 60 else 0.45 if m < 360 else 0.22


# ---------------------------------------------------------------- payload builders
def ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def meta_payload(channel, cust, t, text, mid, echo_app=None, ad_id=None):
    account = PAGE if channel == "messenger" else IG
    if echo_app:
        ev = {"sender": {"id": account}, "recipient": {"id": cust}, "timestamp": ms(t),
              "message": {"mid": mid, "is_echo": True, "app_id": echo_app, "text": text}}
    else:
        ev = {"sender": {"id": cust}, "recipient": {"id": account}, "timestamp": ms(t), "message": {"mid": mid, "text": text}}
        if ad_id:
            ev["referral"] = {"source": "ADS", "type": "OPEN_THREAD", "ad_id": ad_id}
    return {"object": "page" if channel == "messenger" else "instagram",
            "entry": [{"id": account, "time": ms(t), "messaging": [ev]}]}


def wa_payload(cust, name, t, text, mid, echo=False, ad_id=None):
    meta = {"display_phone_number": "639171110000", "phone_number_id": WA}
    if echo:
        value = {"messaging_product": "whatsapp", "metadata": meta, "message_echoes": [
            {"from": "639171110000", "to": cust, "id": mid, "timestamp": str(int(t.timestamp())), "type": "text", "text": {"body": text}}]}
        return {"object": "whatsapp_business_account", "entry": [{"id": "WABA_GLOW", "changes": [{"field": "smb_message_echoes", "value": value}]}]}
    msg = {"from": cust, "id": mid, "timestamp": str(int(t.timestamp())), "type": "text", "text": {"body": text}}
    if ad_id:
        msg["referral"] = {"source_type": "ad", "source_id": ad_id}
    value = {"messaging_product": "whatsapp", "metadata": meta,
             "contacts": [{"profile": {"name": name}, "wa_id": cust}], "messages": [msg]}
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA_GLOW", "changes": [{"field": "messages", "value": value}]}]}


# ---------------------------------------------------------------- scenario generator
def generate(seed: int, days: int, end: datetime) -> tuple[list[tuple], dict]:
    rng = random.Random(seed)
    start = (end - timedelta(days=days)).astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    ai_from = start + timedelta(days=days // 2)
    items, names = [], {}
    n = 0
    for d in range(days):
        day0 = start + timedelta(days=d)
        for _ in range(rng.randint(5, 8)):
            n += 1
            name = NAMES[(n - 1) % len(NAMES)] + ("" if n <= len(NAMES) else f" {n // len(NAMES) + 1}")
            sc_key = rng.choices(list(SCENARIOS), weights=[s["weight"] for s in SCENARIOS.values()])[0]
            sc = SCENARIOS[sc_key]
            channel = sc.get("channel") or rng.choices(["messenger", "instagram"], weights=[70, 30])[0]
            cust = f"639{rng.randint(100000000, 999999999)}" if channel == "whatsapp" else f"PSID{rng.randint(10**9, 10**10)}"
            names[(channel, cust)] = name
            ad_id = ADS.get(sc["interest"]) if rng.random() < 0.65 else None
            hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
            t = day0 + timedelta(hours=hour, minutes=rng.randint(0, 59))
            busy = 0.5 if TZ and t.astimezone(TZ).hour in (12, 13, 18, 19) else 0.0
            for ti, (lines, biz_text) in enumerate(sc["turns"]):
                for li, line in enumerate(lines):
                    items.append((t, "msg", dict(channel=channel, cust=cust, name=name, text=line, out=False,
                                                 ad_id=ad_id if ti == 0 and li == 0 else None)))
                    t += timedelta(seconds=rng.randint(15, 70))
                asked = t
                reply = business_reply(rng, asked, asked >= ai_from, busy)
                if reply is None:
                    break
                rt, who = reply
                app = AI_APP if who == "ai" else INBOX_APP
                items.append((rt, "msg", dict(channel=channel, cust=cust, name=name, text=biz_text, out=True, app=app)))
                if ti < len(sc["turns"]) - 1 and rng.random() > p_continue(rt - asked):
                    break                                 # the customer moved on
                t = rt + timedelta(minutes=rng.randint(2, 40))
            else:
                ref = dict(channel=channel, cust=cust)
                booked_at = t + timedelta(minutes=rng.randint(1, 10))
                if sc["outcome"].startswith("book"):
                    appt = next_open(booked_at) + timedelta(days=rng.randint(0, 2), hours=rng.randint(1, 8))
                    items.append((booked_at, "event", dict(ref, type="consult_booked", props={"appointment_at": appt.isoformat()})))
                    if sc["outcome"] == "book_noshow" or rng.random() < 0.2:
                        items.append((appt + timedelta(minutes=20), "event", dict(ref, type="appointment_no_show")))
                    else:
                        items.append((appt + timedelta(minutes=5), "event", dict(ref, type="appointment_showed")))
                        if rng.random() < 0.85:
                            value = {"botox": 15000, "skin_booster": 14500, "slimming": 30000}.get(sc["interest"], 10000)
                            items.append((appt + timedelta(minutes=rng.randint(40, 90)), "event",
                                          dict(ref, type="payment_received", value=value)))
    items = [i for i in items if i[0] <= end]
    items.sort(key=lambda i: i[0])
    return items, names


def run(url: str | None, seed: int, days: int, reset: bool) -> None:
    from app.db import connect, migrate

    if reset:
        with connect() as c:
            c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            c.commit()
            migrate(c)

    if url:
        import httpx
        http = httpx.Client(base_url=url, timeout=30)
    else:
        from fastapi.testclient import TestClient
        from app.main import app
        http = TestClient(app)

    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    items, names = generate(seed, days, end)
    headers = {"X-Api-Key": API_KEY}
    mid_n = 0
    next_tick = items[0][0]
    sent = 0
    for t, kind, d in items:
        while next_tick <= t:                                 # replay the alert cron
            if in_hours(next_tick):
                http.post("/api/tick", params={"as_of": next_tick.isoformat()}, headers=headers)
            next_tick += timedelta(minutes=5)
        if kind == "msg":
            mid_n += 1
            mid = f"m_{seed}_{mid_n}"
            if d["channel"] == "whatsapp":
                body = wa_payload(d["cust"], d["name"], t, d["text"], f"wamid.{mid}", echo=d["out"], ad_id=d.get("ad_id"))
            else:
                body = meta_payload(d["channel"], d["cust"], t, d["text"], mid,
                                    echo_app=d.get("app") if d["out"] else None, ad_id=d.get("ad_id"))
            raw = json.dumps(body).encode()
            sig = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
            r = http.post("/webhooks/meta", content=raw, headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"})
            r.raise_for_status()
        else:
            ev = {"lead": {"client_id": "demo-clinic", "channel": d["channel"], "external_user_id": d["cust"]},
                  "event_type": d["type"], "occurred_at": t.isoformat(), "value": d.get("value"), "props": d.get("props", {})}
            http.post("/api/events", json=ev, headers=headers).raise_for_status()
        sent += 1
    http.post("/api/tick", params={"as_of": end.isoformat()}, headers=headers)

    # Messenger/IG webhooks carry ids, not names. Production: Graph API profile lookup.
    with connect() as c:
        for (channel, cust), name in names.items():
            c.execute("UPDATE leads SET display_name=%s WHERE channel=%s AND external_user_id=%s AND display_name IS NULL",
                      (name, channel, cust))
        c.commit()
    print(f"replayed {sent} webhooks/events for {len(names)} leads over {days} days (AI after-hours from day {days // 2 + 1})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="post to a running server instead of in-process")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--no-reset", action="store_true")
    args = ap.parse_args()
    run(args.url, args.seed, args.days, not args.no_reset)
