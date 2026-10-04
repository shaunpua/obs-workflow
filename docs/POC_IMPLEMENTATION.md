# POC Implementation Plan

This is the build guide for the clinic POC. It is written so any developer (or a smaller AI model) can pick up one milestone at a time without re-reading the whole conversation.

- **Why and what:** `docs/POC_PLAN.md`
- **What it should look like:** `docs/mockups/client-app.html` (open in a browser; fake data). Every screen below refers to a screen in that mockup.
- **Code:** `poc/`

---

## 0. Decisions this build follows

| Topic | Decision |
|---|---|
| Niche | Clinics only (`poc/config/niches/clinic.yaml`) |
| Inbox | Clinics keep replying in Meta Business Suite / WhatsApp Business app. We only listen (webhooks). No Chatwoot |
| Dashboard data | Source-agnostic. The portal reads only our tables. Meta, booking, payments, events API and CSV are adapters that write into them |
| Frontend | **Our own app**: FastAPI + Jinja2 templates + HTMX, Apache ECharts for charts. No React build step. No Metabase or Grafana in the POC |
| Booking capture | Use the clinic's tool if it has webhooks; else Google Calendar; else CSV; else a staff "Booked" button |
| Database | Postgres 16. Every table has `client_id` |
| LLM | Optional, off by default (`LLM_CLASSIFY=0`). Rules do the labelling |

Not in the POC: AI auto-replies, nurture sequences, WhatsApp, Viber, Metabase, multi-user login with roles, self-serve Meta connect.

---

## 1. Current state (already in `poc/`)

| Works today | File |
|---|---|
| Meta webhook endpoint with signature check, raw storage, dedupe | `app/main.py` |
| Adapters: Messenger, Instagram, WhatsApp (incl. echoes), Chatwoot | `app/normalize.py` |
| One `leads` table (no contacts/journeys split yet), messages, events | `db/001_schema.sql` |
| Reply-time view (first unanswered message rule), business-hours function | `db/002_metrics.sql` |
| Rule classifier hot/warm/cold + optional Claude call | `app/classify.py` |
| Next-action rules, stage tracking | `app/pipeline.py` |
| Alerts: hot unanswered, escalation, silent integration | `app/alerts.py` |
| 14-day simulator posting signed fake webhooks | `scripts/simulate.py` |
| Static dashboard generator | `scripts/build_dashboard.py`, `dashboard/template.html` |

Run it:

```bash
cd poc
pip install -r requirements.txt
docker run -d --name revobs-db -e POSTGRES_USER=revobs -e POSTGRES_PASSWORD=revobs -e POSTGRES_DB=revobs -p 5432:5432 postgres:16
export DATABASE_URL=postgresql://revobs:revobs@localhost:5432/revobs
python -m scripts.simulate
python -m scripts.build_dashboard --standalone
```

---

## 2. Target structure after the POC

```
poc/
  app/
    main.py              # FastAPI app: mounts routers
    settings.py          # env vars (pydantic-settings)
    db.py                # connection pool + migrations runner
    config.py            # niche pack + client file merge (exists)
    ingest/
      meta.py            # /webhooks/meta (moved from main.py)
      events_api.py      # /api/v1/events (generic, any source)
      booking_calcom.py  # /webhooks/booking/calcom (example booking adapter)
      csv_import.py      # CLI + upload: bookings/payments CSV
    core/
      normalize.py       # (exists) platform payload -> canonical message
      identity.py        # contact lookup/merge (NEW)
      journeys.py        # open/continue/close journeys (NEW)
      pipeline.py        # orchestrates: message/event -> contact -> journey -> label -> action
      classify.py        # (exists)
      rules.py           # next actions + custom rules (JSONLogic) (NEW)
      alerts.py          # (exists)
      profiles.py        # Meta User Profile lookup for names (NEW)
    portal/
      routes.py          # HTML pages
      queries.py         # SQL for each screen
      templates/         # base.html, overview.html, queue.html, pipeline.html, contacts.html, contact.html, bottlenecks.html, sources.html
      static/            # app.css (copy tokens from the mockup), htmx.min.js, echarts.min.js
    jobs/
      worker.py          # processes raw_webhooks queue
      scheduler.py       # alerts every minute, refresh hourly
  db/
    001_schema.sql       # (exists, will be replaced by 003)
    002_metrics.sql      # (exists, update for journeys)
    003_contacts_journeys.sql   # NEW
  config/                # (exists)
  scripts/               # simulate.py, build_dashboard.py (keep for demos), backfill_meta.py (NEW)
  tests/                 # pytest, NEW
```

---

## 3. Milestones

Do them in order. Each ends with something you can see. Commit after each.

### M1. Your own Facebook Page live (week 1)

Goal: a real message to your Page and your reply land in Postgres with the right reply time.

Tasks:
1. Add `app/settings.py` reading `DATABASE_URL`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `API_KEY`, `META_PAGE_TOKENS` (JSON map page_id → token).
2. Add `config/clients/<you>.yaml` (copy `demo-clinic.yaml`, put your real Page id under `channels.messenger.external_id`).
3. Add `core/profiles.py`: on first message from a new PSID, call `GET https://graph.facebook.com/v23.0/{psid}?fields=first_name,last_name,profile_pic&access_token=<page token>` and store the name. Cache; never block the webhook on it (do it after the insert, catch errors).
4. Add a `scripts/subscribe_page.py` helper that calls `POST /{page-id}/subscribed_apps?subscribed_fields=messages,message_echoes,messaging_referrals,message_reads`.
5. Write `poc/docs/SETUP_META.md` with the exact clicks you did (app type, product, webhook URL via cloudflared, verify token).

Done when:
- Message from your personal account → one `messages` row `direction='in'`, contact name filled.
- Reply from Business Suite → one row `direction='out'`, `actor='staff'`.
- `SELECT * FROM v_reply_pairs` shows the correct minutes.

### M2. Contacts and journeys (week 2)

Goal: returning customers work. Implements `POC_PLAN.md` §7.

Tasks:
1. `db/003_contacts_journeys.sql`: create `contacts`, `identities`, `journeys` (schema in `POC_PLAN.md` §7.2). Add `contact_id` and `journey_id` to `messages` and `events`. Migrate existing `leads` rows: one contact + one identity + one journey each. Keep `leads` as a view for compatibility until the portal is switched.
2. `core/identity.py`: `find_or_create_contact(client_id, kind, value, name=None)`. Exact match on `identities`. If a later event carries a phone/email that matches another contact, **don't auto-merge different channel ids**; insert a row into `merge_suggestions` instead.
3. `core/journeys.py`: `journey_for(contact, at, cfg)` with the rule: new journey if none, last outcome won/lost, or quiet > `new_journey_after_days` (add `new_journey_after_days: 45` to `clinic.yaml`). Set `returning=true` when the contact had a previous journey. Close a journey as `won` on `payment_received`, `lost` on `lead_lost`.
4. Move stage, temperature, next action, `awaiting_reply` from leads to journeys in `pipeline.py`.
5. Update `002_metrics.sql` views to group by `journey_id` instead of `lead_id`.
6. Update `simulate.py` to include ~15% returning patients (second journey 2–6 months after a paid first one).

Done when (pytest):
- Same PSID, message 60 days after a won journey → same contact, journey number 2, `returning = true`.
- Same PSID, message 10 days after an open journey → same journey.
- Reply times computed per journey.

### M3. Any-source events + booking capture (week 3)

Goal: bookings and payments from sources other than Meta. Implements `POC_PLAN.md` §10.1.

Tasks:
1. `ingest/events_api.py`: `POST /api/v1/events` exactly as in the plan (per-client API key in `clients/*.yaml` as `api_key_env`, `Idempotency-Key` header → `events.dedupe_key`). Contact match order from `contact_match`. If no contact matches, create one with `source = <api key name>` (walk-ins).
2. `event_mapping` in the client file: translate their words ("Paid") to ours (`payment_received`).
3. `ingest/booking_calcom.py`: Cal.com `BOOKING_CREATED`, `BOOKING_CANCELLED`, `BOOKING_RESCHEDULED` → `consult_booked` / `consult_cancelled`. Verify the Cal.com webhook secret. Match contact by attendee phone/email; else by a `jid` query param you put in the booking link.
4. `ingest/csv_import.py`: `python -m app.ingest.csv_import --client glow --kind payments file.csv` with columns `date,phone,amount,reference`. Same matching rules.
5. Add a `source` column to `events` and show it everywhere.

Done when:
- A `curl` to `/api/v1/events` marks a journey paid and it shows up in revenue.
- Re-sending the same `Idempotency-Key` does nothing.
- A CSV of 3 payments imports with 3 events, matched by phone.

### M4. Portal v1 (weeks 4–5)

Goal: the mockup, with real data. Copy the CSS tokens and layout from `docs/mockups/client-app.html`.

Screens (each a Jinja template + one query function in `portal/queries.py`):

| Screen | Route | Query source | Notes |
|---|---|---|---|
| Overview | `/c/{client}/` | `v_daily_kpis`, `v_reply_pairs`, journeys, events | KPI tiles, reply-time chart (ECharts, log y), inquiries by hour, leaks table, sources table |
| Action queue | `/c/{client}/queue` | journeys where `next_action_priority <= 3` | HTMX auto-refresh every 30s (`hx-trigger="every 30s"`). Buttons POST to `/c/{client}/journeys/{id}/mark` |
| Pipeline | `/c/{client}/pipeline` | open journeys by stage | No drag-and-drop in the POC |
| Contacts | `/c/{client}/contacts` | contacts + latest journey | Filters as query params; HTMX swaps the table |
| Contact profile | `/c/{client}/contacts/{id}` | contact, journeys, `lead_trace()` | Journey tabs, trace bars, conversation |
| Bottlenecks | `/c/{client}/bottlenecks` | stage milestones | Funnel with % kept and median/p90 per step |
| Sources & rules | `/c/{client}/sources` | channels, last event per source | Shows "last event received" per source (health) |

Auth for the POC: one shared password per client (HTTP Basic or a signed cookie). Real users and roles come later.

"Mark booked / arrived / paid" buttons create events with `source='portal'`.

Done when: every mockup screen renders from the simulator's data and from your own Page's data.

### M5. Alerts and weekly digest (week 5)

1. `jobs/scheduler.py` with APScheduler: `run_checks` every minute, `refresh_all` hourly, digest Mondays 08:00 Manila.
2. Telegram: env `TELEGRAM_BOT_TOKEN`; per client `alerts.front_desk.chat_id_env`. Message includes a link to the contact profile.
3. Digest: 3 numbers (median first reply, booked, revenue) vs last week + top 3 actions, sent to the owner chat.

Done when: a test hot lead on your Page pings your phone within 10 business minutes, and the digest arrives.

### M6. Hardening (week 6)

1. `jobs/worker.py`: webhook endpoint only stores raw and returns 200; worker processes with `SELECT … FOR UPDATE SKIP LOCKED`.
2. `scripts/backfill_meta.py`: conversations API → contacts + last 20 messages each, `source='backfill'`, excluded from baseline metrics.
3. Classifier check: export 100 conversations to CSV, hand-label, `scripts/eval_labels.py` prints accuracy per label.
4. Docker Compose: `db`, `app`, `worker`, `scheduler`, `caddy`.

---

## 4. Conventions

- Python 3.11, FastAPI, psycopg 3, pydantic v2. Format with `ruff format`, lint with `ruff check`.
- SQL lives in `db/*.sql` (schema, views) and `portal/queries.py` (screen queries). No ORM.
- Every table and every query filters by `client_id`.
- Times: store `timestamptz` in UTC; convert to the client's timezone only in SQL views or templates.
- Never block a webhook response on an external call (Graph API, LLM, Telegram).
- Every new behaviour gets a pytest using `scripts/simulate.py` payload builders or small fixtures.
- Don't put niche words (botox, solar) in Python. They belong in YAML.
- Secrets only in env vars; never in YAML or git.

## 5. Definition of done for the POC

- Your own Page connected, real messages and replies tracked.
- Simulated clinic with 30 days of data, including returning patients, bookings from Cal.com webhooks and payments from the events API.
- Portal shows all mockup screens with real queries, usable on a phone.
- Hot-lead alert and weekly digest arrive on Telegram.
- A 10-minute demo script you can show a clinic owner.
