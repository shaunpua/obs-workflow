# Handoff — obs-workflow (Revenue Observability POC) — 2026-10-11
Written by: Claude Code (Sonnet 5.5) on the owner's laptop, then committed so a cloud session can pick it up. Repo `github.com/shaunpua/obs-workflow`, branch `claude/modest-bell-s4qaoo`.
Unrelated to PocketHost / Airbnb automation / lorealdbaly. Do not share code, env or DB credentials with them.

## What this is
A service: connect a business's Facebook Page (later Instagram/WhatsApp), measure reply times from Meta webhooks, label leads, keep a lead database,
show dashboards/alerts. Master plan `docs/POC_PLAN.md`; index `docs/README.md`. First client = the owner's own Page
**BackHome Short Term Rentals** (Page ID `1063474886839617`, client id `my-airbnb`, hours 07:00–23:00 Asia/Manila).

## Result so far — M1 is PROVEN end to end on a real Page
- Real Messenger webhooks → Cloudflare quick tunnel → FastAPI app → Postgres, signed (X-Hub-Signature-256) and stored raw first.
- Customer messages AND the owner's Business Suite inbox replies (echoes, `app_id` 263902037430900) are both captured; reply pairs and business-hours-aware
  minutes computed (`v_reply_pairs`, `v_daily_kpis`); lead labelled by rules (hot/warm/cold + intent). Guest name resolved.
- Tester account used: "Alyssa Villacruz Ong" (PSID `40110389905214604`). A Page admin can't message their own Page as a customer.
- Meta app: Business type, linked to portfolio BackhomeBGC; Messenger use case added; webhook verified; Page subscribed to 4+ fields then widened
  (messages, message_echoes, message_reads, message_deliveries, messaging_referrals, postbacks, handovers, policy_enforcement, customer_information, edits, standby,
  plus the optional ones: inbox_labels, reactions, optins/optouts, in_thread_lead_form_submit, calls*). App stays in **Development mode** (no app review needed for testers).
- Permissions seen "Ready for testing": pages_messaging, pages_manage_metadata, pages_read_engagement, pages_show_list, business_management, instagram_basic.
- 10 tests pass. Local stack was verified; **it is now stopped** (see "Run it").

## What was built this session (all uncommitted)
- Local setup for VS Code: ports moved off 8000/5432/3000 (app **8765**, DB **55432**, Grafana **3100**); `.env` auto-loaded; `check_env` (uses `debug_token`, not the Page name);
  `.env.example` with `>>> FILL <<<` markers; run buttons/tasks; `.venv` built without ensurepip (needs `sudo apt install python3.10-venv` to recreate normally).
- `poc/app/admin.py`: plain `/admin` (metrics), `/admin/logs`, `/admin/leads`, `/admin/trace/<lead>`; key = `API_KEY` (`?key=`). httpx request logging silenced (it logged the Page token).
- Grafana (docker, localhost only) with a provisioned "Revenue Observability" dashboard (14 panels incl. per-lead trace dropdown); read-only DB login `revobs_ro` (`db/003_readonly.sql`).
- `profiles.py`: guest name via `GET /{page}/conversations?user_id=…&fields=participants` fallback (the per-PSID profile call is refused); retry at most every 10 min.
- `config.py`: channel sync now deletes channel ids no longer in a client's YAML (a stale `change-me` row had broken name lookup).
- Docs reorganised: `docs/business/` (BUSINESS_MODEL, CLIENT_ONBOARDING, SERVICE_OPERATIONS, reference/ transcript) and `docs/tech/` (ARCHITECTURE, POC_IMPLEMENTATION,
  PRODUCT_UX, BUILD_VS_BUY, mockups, `ops/` = LOCAL_SETUP, SETUP_META, RUNBOOK). All internal links verified.

## Known issues / not built (in priority order)
1. **Meta's automatic "away" reply is counted as the first staff reply** (same inbox app id as human replies) → first-reply times look like 0.1 min. Needs a per-client
   "ignore replies matching this text/pattern" rule (config + normalize/pipeline + test). Highest-value fix.
2. Attachments, shared links, images are ignored (only message text stored). Contact details (phone/email) are never captured: Messenger doesn't provide them — extract from
   message text, and/or read `messaging_customer_information` / `messaging_in_thread_lead_form_submit` payloads (not yet seen in real data).
3. Read/delivery/postback/etc. webhooks are stored raw but not processed. Calls (`calls`, `call_permission_reply`) unverified.
4. Tunnel is a throwaway quick tunnel: new URL every restart → must re-paste Callback URL in Meta. Needs a fixed address (named Cloudflare tunnel with a domain, ngrok free
   domain, or hosting). A VPN can block cloudflared (QUIC and :7844).
5. M2 (contacts vs journeys split, returning guests) not started. M3+ per `docs/tech/POC_IMPLEMENTATION.md`.
6. Instagram / WhatsApp: code paths exist, never tested live.
7. Business verification + app review for clients' Pages not started (critical path for any non-tester client).
8. The Page token was partially printed in a chat transcript once → **regenerate `META_PAGE_TOKEN`** (Messenger API settings → Generate) and update `poc/.env`.
9. `docs/business/reference/first-10k-client-webinar.txt` is someone else's transcript: consider `.gitignore`.

## Run it (from `poc/`)
1. `docker compose up -d db grafana` (DB volume `revobs-data` keeps ~13 stored webhooks unless pruned).
2. VS Code Run and Debug → "App: run the webhook server" (or `.venv/bin/uvicorn app.main:app --port 8765`).
3. `~/.local/bin/cloudflared tunnel --url http://localhost:8765` → `python -m scripts.check_env --url https://<tunnel>` → paste `https://<tunnel>/webhooks/meta` + `META_VERIFY_TOKEN`
   into Meta (Messenger API settings → 1. Configure webhooks → Verify and save).
4. Look: `http://localhost:8765/admin?key=<API_KEY>` and `http://localhost:3100`. Tests: `.venv/bin/python -m pytest tests -q` (uses DB `revobs_test` in the same container; create it once).
`poc/.env` holds the real Meta secrets (git-ignored). Never print or commit them.

## Cloud-session notes
- A cloud session has NO secrets, no Meta access, no tunnel and no Docker: work with simulated webhooks (`python -m scripts.simulate`, `scripts.send_test_message`) and signed fake payloads in tests.
- Tests: set `DATABASE_URL` to the sandbox Postgres, e.g. `postgresql://postgres@/revobs_test?host=/var/tmp/pgpoc&port=5433` (the repo default points at the laptop's Docker DB on :55432).
- Live checks against Meta (real messages, webhook verify, subscriptions) can only be done on the laptop; leave them as a to-do for the owner.
- `docs/business/reference/` (a third-party transcript) is git-ignored and not in the repo.

## Decisions the owner still has to make
- Dashboards: keep Grafana for internal logs/traces (recommended); client-facing screens later in our own page (ECharts). Metabase only if clients should self-serve charts.
- Fixed tunnel/hosting choice. Whether to start Meta business verification now (recommended).
- Business model (`docs/business/BUSINESS_MODEL.md`, DRAFT): sell ONE outcome ("stop losing Messenger inquiries; see what slow replies cost"); observability + lead DB + alerts as one bundle;
  workflow agent / collectors / reactivation as upsells; do NOT sell new-lead generation yet; run BackHome 2–4 weeks as case study #1; paid audit as the door-opener.

## Suggested next steps
1. Fix the auto-reply counting (issue 1) with tests. 3. Capture attachments + links + phone/email-from-text (issue 2).
4. Fixed webhook URL / hosting (laptop/owner). 5. Let BackHome run 2–4 weeks for a baseline. 6. M2.

## Hard rules for this task
- Never print or commit `poc/.env`, the app secret, the Page token or `API_KEY`.
- The Page is the owner's REAL business Page. App is in Development mode, so only users with an app role can reach it; still, never send messages to guests from code without an explicit ask.
- Ports: don't use 8000/5432/3000 (other projects here use them). Use 8765 / 55432 / 3100.
- Run the repo's tests before saying done; don't claim a UI change works without opening it.
