# Architecture (as built in `poc/`)

What runs today, how data flows, which outside APIs we call, and where each piece lives in the code.
The full design and the reasons behind it are in [`../POC_PLAN.md`](../POC_PLAN.md) sections 2, 7 and 10.

## Data flow

```
Guest ──► Page / IG / WhatsApp ──► Meta ──POST /webhooks/meta (signed)──► app
Staff reply in Business Suite ──► Meta ──echo webhook─────────────────────┘
                                                                          │
   raw_webhooks (stored first, as received)  ◄────────────────────────────┤
   normalize → pipeline: leads, messages, events, lead_labels             │
   SQL views: v_reply_pairs, v_lead_milestones, v_daily_kpis              │
                                                                          ▼
   /admin pages (app)   Grafana :3100 (read-only login)   /api/* (API key)   alerts → Telegram
```

Rule: store the raw webhook before doing anything else, so parsing changes can be re-run on old data.

## Components and ports (local)

| Component | Where | Port |
|---|---|---|
| App (FastAPI + uvicorn) | `poc/app/` | 8765 |
| Postgres 16 (Docker `revobs-db`) | `poc/docker-compose.yml`, schema in `poc/db/*.sql` | 55432 |
| Grafana (Docker `revobs-grafana`, localhost only) | `poc/grafana/` | 3100 |
| Public tunnel (cloudflared quick tunnel) | run by hand | random `*.trycloudflare.com`, changes on restart |

Ports avoid 3000/5432/8000 used by other projects on this machine.

## Code map

| File | Job |
|---|---|
| `app/main.py` | HTTP routes: Meta webhook (verify + signed POST), Chatwoot webhook, `/api/events`, `/api/tick`, `/api/leads`, `/api/leads/{id}/trace`, `/health` |
| `app/normalize.py` | Channel payload → one message shape (Messenger/IG, WhatsApp, Chatwoot). Reads, deliveries etc. are skipped (kept raw) |
| `app/pipeline.py` | Leads, messages, events; stage, next action, trace |
| `app/classify.py` | Hot/warm/cold from niche keyword rules; optional LLM (`LLM_CLASSIFY=1`) |
| `app/alerts.py` | Alert checks (`/api/tick`), Telegram or console |
| `app/profiles.py` | Fills guest names after the webhook is answered |
| `app/config.py` | Niche pack + client YAML → merged config; syncs clients/channels to the DB |
| `app/admin.py` | Plain `/admin` pages: metrics, logs, leads, trace |
| `config/niches/*.yaml`, `config/clients/*.yaml` | All niche/client specifics (no niche words in code) |

## Data model (tables)

| Table | One row per | Notes |
|---|---|---|
| `clients` | business we serve | hours, timezone, merged config |
| `channels` | Page / IG account / WhatsApp number | routes a webhook to a client |
| `raw_webhooks` | request received | payload, signature ok, processed, error |
| `leads` | person per client per channel | stage, temperature, score, intent, waiting since |
| `messages` | message, both directions | `actor` = customer / staff / ai; `app_id` tells AI echoes from inbox echoes |
| `events` | business event (append-only) | the trace; bookings/payments arrive via `/api/events` |
| `lead_labels` | classification | history for auditing accuracy |
| `alerts` | alert fired | one open alert per lead and type |

Planned next (M2): split `leads` into contacts + journeys so returning guests are recognised (`POC_PLAN.md` §7).

## Outside APIs we call

| API | Used for | Permission it needs |
|---|---|---|
| Meta webhooks (inbound) | messages, echoes, reads, deliveries, referrals… | Page subscribed to the fields |
| Graph `GET /{page_id}/conversations?user_id=…&fields=participants` | guest name (works with our token) | `pages_messaging` |
| Graph `GET /{psid}?fields=first_name,last_name` | guest name (tried first; refused for us so far) | profile access feature |
| Graph `GET /debug_token` | `check_env`: token valid, right Page, scopes | app id + secret |
| Graph `POST/GET /{page_id}/subscribed_apps` | subscribe the Page (script) | `pages_manage_metadata` (our token lacks it; done in the dashboard instead) |
| Telegram `sendMessage` | alerts | bot token |

Graph version is pinned with `GRAPH_VERSION` (default `v23.0`).

## Security

- Webhook POSTs are rejected unless the `X-Hub-Signature-256` matches `META_APP_SECRET`.
- `/admin` and `/api/*` need `API_KEY` (the tunnel makes the whole app public).
- Grafana is bound to localhost and reads through `revobs_ro` (SELECT only). Local passwords; change them before hosting.
- The `httpx` request log is silenced because Graph URLs carry the Page token.
- Secrets live only in `poc/.env` (git-ignored).
