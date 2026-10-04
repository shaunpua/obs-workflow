# Revenue Observability: POC Plan (v2)

Status: **plan agreed in part** (see section 18 for decisions). A first version of the code is in `poc/`, paused until this plan is agreed.
v2 adds: everything you can pull from Messenger/Instagram/WhatsApp/Viber, backfilling old chats, returning customers, how to view leads, custom per-client logic, the tech stack, an LLM-council review, and references.

---

## Contents

1. The idea and how a client uses it
2. Tech stack and architecture
3. What data you can get from each channel
4. Old data: what can be backfilled
5. Sample flows
6. What you get: metrics, labels, traces, bottlenecks, actions, alerts
7. Leads: contacts, journeys, returning customers, and how to view them
8. Showing data to clients: build or reuse
9. Flexibility: config layers
10. Custom per-client logic (APIs, payments, custom rules)
11. Client onboarding system
12. Translating a client's workflow into the system
13. WhatsApp and Viber
14. Test it on your own Facebook Page
15. Scalability and cost
16. Risks
17. LLM council review
18. Roadmap and decisions
19. References

---

## 1. The idea and how a client uses it

Meta sends **your server** a copy of every customer message and every reply the business sends, including replies staff type by hand in the inbox. From those you compute reply speed, label leads hot/warm/cold, track each customer's journey, alert staff and suggest the next action. The client keeps working the way they do today.

```
Customer → Page / IG / WhatsApp → Meta → webhook → YOUR APP → alerts, digest, dashboard, action queue
Staff reply as usual in the inbox ─────┘ (the reply comes back as an "echo" webhook)
```

What the client does: give Page access, keep replying as usual, use a booking link or tap "Booked / Arrived / Paid", act on alerts.

---

## 2. Tech stack and architecture

### 2.1 Layers

```
SOURCES      Messenger · Instagram · WhatsApp · Lead Ads · booking · payments · client systems
   │ webhooks (push)        │ Graph/Marketing API (pull: profiles, history, ad spend)
INGEST       FastAPI endpoints → verify signature → raw_webhooks → queue
   │
WORKERS      normalize → identity → lead/journey update → classify → stage → next action
   │                                       ▲ config: niche pack + client file + custom rules
STORE        Postgres: contacts, identities, journeys, messages, events, labels, alerts
   │
METRICS      SQL views (reply times, funnel, time-in-step, source→revenue, cohorts)
   │
OUTPUTS      client portal (action queue, pipeline, contact timeline) · Metabase charts
             · Telegram/Viber/email alerts + weekly digest · outbound webhooks to client systems
OPS          Prometheus + Grafana (your own monitoring) · Sentry · uptime + heartbeats
```

### 2.2 Stack choices

| Layer | POC (now) | v1 (first paying clients) | Why |
|---|---|---|---|
| Language / API | Python + FastAPI | same | Fast to build, good Meta/LLM libraries, already written |
| Database | Postgres 16 | Postgres 16 (managed or on the VPS, daily backups) | One store for leads, events and metrics; SQL views feed every dashboard |
| Queue | none (inline) | Postgres queue (`SELECT … FOR UPDATE SKIP LOCKED`) or Redis + RQ | Return 200 to Meta fast; retry failures |
| Scheduler | `/api/tick` | cron container or APScheduler | Alerts every minute, decay hourly, digest weekly |
| Client portal | static HTML generated from SQL | server-rendered app (FastAPI + Jinja + HTMX) or Next.js; charts with Apache ECharts or Chart.js | Action queue, pipeline and contact timeline are custom screens no BI tool does well |
| Analytics charts | inside the portal | Metabase OSS, static (signed) embeds locked to `client_id` | Free; drag-and-drop questions for you |
| Your ops monitoring | logs | Prometheus + Grafana + Uptime Kuma; Sentry for errors | You know these; monitors webhooks, queue depth, token health |
| Alerts | console / Telegram | Telegram bot (free), Viber bot (paid, see §13), email | Where staff already are |
| LLM | Claude (optional) | Claude, only for unclear leads | Rules first keeps cost low |
| Hosting | laptop + tunnel | one VPS with Docker Compose + Caddy (auto HTTPS) | Cheap, simple, enough for ~50 clients |
| Secrets | env vars | Infisical or Doppler | Page tokens per client |
| Automations | — | n8n (self-hosted) for one-off client workflows | Keeps custom glue out of the core |

### 2.3 Data model v2 (adds contacts and journeys)

| Table | One row per | Notes |
|---|---|---|
| `contacts` | real person per client | Name, phone/email if given, first seen, lifetime value, tags (VIP, returning) |
| `identities` | channel id of a person | PSID (Messenger), IGSID (Instagram), wa_id (WhatsApp), phone, email. Several per contact |
| `journeys` | one buying cycle | Stage, temperature, interest, value, outcome (won/lost/open), journey number |
| `messages` | message | Linked to contact and journey |
| `events` | thing that happened | Append-only trace: lead_created, first_reply, booked, paid, alert_fired… |
| `raw_webhooks` | webhook as received | Re-process when parsing changes |
| `lead_labels` | label change | Accuracy audits |

In the POC code these are merged into one `leads` table. v1 splits it so returning customers work (section 7).

---

## 3. What data you can get from each channel

### 3.1 Messenger (Facebook Page)

**Webhooks (pushed to you in real time)** — subscribe per Page ([webhook reference](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks)):

| Webhook field | What it contains | What you use it for |
|---|---|---|
| `messages` | Customer's text, attachments (image, video, audio, file, location, sticker), quick-reply payload, reply-to, timestamp, sender PSID. First message from a click-to-Messenger ad carries a `referral` with the `ad_id` | Inbound log, labels, attribution |
| `message_echoes` | Every message the **Page** sends, with `is_echo` and the `app_id` of the tool that sent it | Reply times, AI vs staff split |
| `messaging_referrals` | User arrived via an m.me link with `ref`, an ad, or a chat plugin, in an existing thread | Campaign/QR-code attribution for returning chats |
| `messaging_postbacks` | Button / Get Started / persistent menu taps | Funnel steps inside the chat |
| `message_reads` | Customer read the Page's messages up to a timestamp | "Seen but no reply" detection |
| `message_deliveries` | Page messages delivered | Delivery issues |
| `message_reactions` | Customer reacted to a message | Sentiment signal |
| `messaging_optins` | Customer opted in to notifications | Permission for follow-ups outside 24h |
| `messaging_handovers`, `standby` | Thread control passed between apps (e.g. your bot and the Page inbox) | Knowing who "owns" a conversation |
| `leadgen` (Page field) | A Lead Ads form was submitted; gives a `leadgen_id` you then fetch ([Lead Ads retrieval](https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving)) | Form leads in the same lead DB |

**APIs you call (pull):**

| API | What you get | Notes |
|---|---|---|
| User Profile (`GET /{PSID}?fields=first_name,last_name,profile_pic`) | Name and photo for a PSID | Names aren't in the webhook; fetch once per new contact |
| Conversations API (`GET /{page-id}/conversations?platform=messenger`) | Conversation list with last update time, message ids and timestamps | **Message details only for the 20 most recent messages per conversation** ([Conversations API](https://developers.facebook.com/docs/messenger-platform/conversations/)) |
| Marketing API insights | Spend, impressions and clicks per campaign/ad per day | CAC and ROAS per ad |
| Send API | Send replies, quick replies, buttons | AI responder and nurture (phase 2) |

**What you can't get:** chats on staff's **personal** Messenger accounts; the customer's phone or email unless they type it or fill a form; messages from before your app was connected beyond what the Conversations API returns.

**Rules that limit sending:** free-form messages within 24h of the customer's last message; after that only approved message tags, e.g. `HUMAN_AGENT` lets a person reply up to 7 days, and tags can't be promotional ([Messenger policy](https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy), [send messages](https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages)).

### 3.2 Instagram (professional account linked to the Page)

Same webhook URL and similar events: `messages` (business's own sent messages also arrive here, flagged `is_echo`), `messaging_seen`, `messaging_referral`, `messaging_postbacks`, reactions. The separate `message_echoes` field is Messenger-only ([Meta webhooks for messaging](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks)). The Conversations API takes `platform=instagram`. Comments on posts and ads are a separate webhook (`comments`), useful later for "comment → DM" funnels.

### 3.3 WhatsApp

See section 13. Short version: Cloud API webhooks give customer messages and delivery/read statuses. With **Coexistence** (business keeps the WhatsApp Business phone app) you also get `smb_message_echoes` for replies typed on the phone and a one-time `history` webhook of past chats ([Onboard WhatsApp Business app users](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/), [360dialog coexistence webhooks](https://docs.360dialog.com/partner/onboarding/whatsapp-coexistence/coexistence-webhooks)).

### 3.4 Summary

| Data | Messenger | Instagram | WhatsApp (Coexistence) | Viber bot |
|---|---|---|---|---|
| Customer messages | ✅ | ✅ | ✅ | ✅ |
| Staff replies typed by hand | ✅ echoes | ✅ is_echo | ✅ smb_message_echoes | ❌ only replies sent through the bot/tool |
| AI vs human | ✅ app_id | ✅ app_id | ✅ (your sends vs echoes) | ✅ (all via your tool) |
| Ad attribution | ✅ referral | ✅ referral | ✅ referral on click-to-WhatsApp | ❌ |
| Read receipts | ✅ | ✅ | ✅ statuses | ✅ |
| Customer name | Profile API | Profile API | in webhook | in webhook |
| Phone number | only if given | only if given | ✅ always | ❌ (Viber id) |
| Past history | last 20 msgs/conversation | last 20 msgs/conversation | up to ~6 months, once at onboarding | ❌ |

---

## 4. Old data: what can be backfilled

| Channel | What you can pull | How to use it |
|---|---|---|
| Messenger / Instagram | Every conversation with its last-updated time; full details for the **last 20 messages** of each | Build the contact list, flag past customers, rough "last 90 days" volume. Not enough for exact historical reply times on long threads |
| WhatsApp Coexistence | `history` webhook: up to ~180 days of chats, sent once after the business approves sharing ([360dialog](https://docs.360dialog.com/partner/onboarding/whatsapp-coexistence/coexistence-webhooks)) | A real baseline before you change anything |
| Booking / POS / spreadsheets | CSV or API export | Match by phone/email to mark returning customers and lifetime value |
| Lead Ads | Leads from the form (retention window applies; fetch soon after onboarding) | Add to contacts |

**Recommendation:** at onboarding run a one-time backfill job (conversations → contacts → last 20 messages each, marked `source=backfill`). Then measure live for 1–2 weeks as the clean baseline. Never mix backfilled reply times into the baseline numbers.

```python
# Backfill sketch: page conversations → contacts + recent messages
def backfill_page(page_id, token, since):
    url = f"https://graph.facebook.com/v23.0/{page_id}/conversations"
    params = {"platform": "messenger", "fields": "id,updated_time,participants,messages.limit(20){id,created_time,from,message}",
              "access_token": token}
    while url:
        page = httpx.get(url, params=params).json()
        for conv in page["data"]:
            if conv["updated_time"] < since: return
            upsert_contact_from_participants(conv["participants"])
            for m in conv.get("messages", {}).get("data", []):
                insert_message(m, source="backfill")        # dedupe by message id
        url, params = page.get("paging", {}).get("next"), None
```

(Pin the Graph API version you test against; field names can change between versions.)

---

## 5. Sample flows

### Flow A: night message, answered next morning

| Time | What happens | What the system records |
|---|---|---|
| 21:14:05 | Ana: "Hi! Magkano po botox?" (from the Botox ad) | `messages` webhook → contact + journey #1, source `AD_BOTOX_OCT`, **warm**, waiting since 21:14 |
| 21:15:10 | "Available po ba bukas? Pa-book sana" | Same wait. Score 80 → **hot**, `lead_qualified` |
| 09:00 | Clinic opens | Alert check: hot, 10 business minutes → Telegram to front desk |
| 09:12:40 | Staff replies in Business Suite | `message_echoes` (inbox app_id → staff). First reply **11h 58m raw, 12m business**. Alert resolved |
| 09:20 | Ana books via link | `consult_booked`, stage booked, reminders queued |
| next day | Shows up, pays ₱15,000 | `appointment_showed`, `payment_received`, journey **won**, revenue credited to the ad |

### Flow B: same lead with AI after hours

AI replies at 21:15 via the Send API; the echo carries **your** app_id → actor `ai`. In the 14-day simulation, median first reply went from 7h 25m to 10m and consults booked from 7 to 12.

### Flow C: price shopper goes cold

"hm po filler" → price 3h later → "ok po thanks" → silence. Rules: price-only → **cold** → monthly promo list. The trace shows it died right after a price with no booking ask.

### Flow D: returning customer (new)

| When | What happens | What the system records |
|---|---|---|
| Oct 2025 | Ana books and pays for Botox (journey #1, won) | Contact Ana, LTV ₱15,000 |
| Feb 2026 | Ana messages the same Page again: "Pa-book ulit po" | Same PSID → **same contact**. Journey #1 is closed, so **journey #2** opens, tagged `returning`. Label starts with a returning-customer bonus |
| | Dashboard | Shows "Returning customer · 1 past visit · ₱15,000 lifetime". Next action: "Rebook with her usual doctor" |

---

## 6. What you get

### 6.1 Metrics

| Metric | Definition |
|---|---|
| First response time | First business reply − first customer message of the journey |
| Response time per turn | Reply − **first unanswered** customer message (3 messages in a row = 1 wait) |
| Business-hours vs raw | Same wait counting only open hours vs wall-clock |
| p50 / p90 | Median and worst 10% |
| Unanswered rate | Journeys with no business reply |
| AI vs staff | From the echo `app_id` |
| Stage conversion + time per step | Funnel and bottlenecks |
| Source → revenue | Ad id on first message → payments |
| Returning rate, LTV | Contacts with 2+ journeys; revenue per contact |

### 6.2 Classification

Weighted keyword rules per niche (`asks_to_book +45`, `asks_availability +35`, `asks_location +20`, `price_only +8`, `not_now −25`, `gone_cold −40`; ≥50 hot, ≥20 warm). Quiet 3 days drops one level (not for booked/paid). An LLM (Claude, structured JSON) only checks unclear leads. Validate on 100 hand-labelled chats.

### 6.3 Traces, bottlenecks, actions, alerts

- **Trace**: a journey's messages + events on one timeline, with the gap since the previous step; gaps over SLA in red.
- **Bottlenecks**: % kept per stage + median/p90 time per step; biggest drop flagged. Plus inquiries by hour vs opening hours.
- **Next actions**: ordered rules in the niche file, first match wins (e.g. "hot + waiting → reply now, offer 2 slots").
- **Alerts**: hot unanswered 10 business min → front desk; any lead 30 min → manager; no messages 6h in open hours → you.

---

## 7. Leads: contacts, journeys, returning customers, and how to view them

### 7.1 The model in plain words

- A **contact** is a person (Ana). One contact can have several channel ids (Messenger PSID, IG id, WhatsApp number).
- A **journey** is one attempt to buy (Ana's Botox in October; Ana's filler in February). Stage, temperature and next action belong to the journey, not the person.
- **Messages and events** attach to the contact and to the journey that was open at that time.

So the lead DB is **a customer database (contacts) plus their journeys (what phase each purchase is in)**.

### 7.2 Recurring customers: rules

1. **Same chat id = same person.** A Messenger PSID is fixed for that person on that Page, so a message a year later maps to the same contact automatically. Same for IG ids and WhatsApp numbers.
2. **Cross-channel:** merge automatically only on an exact phone/email match. Similar names → suggest a merge for staff to confirm.
3. **New journey vs same journey** (configurable per niche):
   - the last journey is won or lost → new journey
   - or the last message was more than `new_journey_after_days` ago (clinic 45, solar 120, real estate 180) → new journey
   - otherwise → continue the open journey
4. New journeys of known contacts get `returning = true`, their history and lifetime value, and a niche-specific next action (rebook, upsell, referral ask).

```sql
CREATE TABLE contacts   (contact_id uuid PRIMARY KEY, client_id text, name text, phone text, email text,
                         first_seen timestamptz, lifetime_value numeric DEFAULT 0, tags text[]);
CREATE TABLE identities (client_id text, kind text, value text, contact_id uuid,   -- kind: psid | igsid | wa_id | phone | email
                         PRIMARY KEY (client_id, kind, value));
CREATE TABLE journeys   (journey_id uuid PRIMARY KEY, contact_id uuid, client_id text, number int,
                         opened_at timestamptz, closed_at timestamptz, outcome text,   -- open | won | lost
                         stage text, temperature text, interest text, value numeric, returning boolean,
                         next_action text);
```

```python
def journey_for(contact, msg_time, cfg):
    j = latest_journey(contact)
    gap_days = (msg_time - j.last_activity).days if j else None
    if j is None or j.outcome in ("won", "lost") or gap_days > cfg["new_journey_after_days"]:
        return open_journey(contact, number=(j.number + 1 if j else 1), returning=j is not None)
    return j
```

### 7.3 How to view leads: four views, each for one job

| View | Who | Question it answers | Looks like |
|---|---|---|---|
| **Action queue** (home screen) | front desk | "Who do I message right now?" | Sorted list: priority, name, hot/warm/cold chip, waiting time, next action, one-tap "open chat" |
| **Pipeline board** | owner / sales lead | "How many deals are in each phase?" | Kanban columns by stage (Inquiry → Replied → Qualified → Booked → Showed → Paid), card = journey, colour = temperature |
| **Contact profile** | anyone | "Who is this person and what happened?" | Header (name, channels, LTV, returning badge) + journey list + trace timeline |
| **Contacts table** | owner / marketing | "Give me everyone who…" | Filterable table: segment by interest, last visit, spend, temperature; export for promos |

Wireframe of the action queue:

```
┌ Today ─────────────────────────────────────────── 3 hot · 6 warm · 41 cold ┐
│ P1  Ana R.      ● HOT   waiting 12m   Botox   ₱15k  Reply now: offer 2 slots  [Open chat] │
│ P1  Bea S.      ● HOT   booked? no    Filler  ₱25k  Close it today: send link   [Open chat] │
│ P2  Carla D.  ↺ returning · last visit Mar · Laser  Rebook: 4 months since last [Open chat] │
│ P2  Dianne      ● WARM  quiet 26h     Laser   ₱8k   Follow up with promo        [Open chat] │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Showing data to clients: build or reuse

| Option | Licence / cost | Good for | Limits |
|---|---|---|---|
| **Own portal** (FastAPI + HTMX or Next.js, ECharts) | your time | Action queue, pipeline, contact timeline, branding, future SaaS | You build and maintain it |
| **Metabase OSS** | free, self-host | Charts and KPI dashboards from SQL; static signed embeds | Static embeds are view-only with a "Powered by Metabase" badge; interactive embedding, row-level permissions and white-labelling need Pro ([securing embeds](https://www.metabase.com/docs/latest/embedding/securing-embeds)) |
| **Grafana OSS** | free (AGPLv3) | Your own ops monitoring and alert rules; time series | Panel embedding needs anonymous access or public dashboards; feels technical to owners ([sharing dashboards](https://grafana.com/docs/grafana/latest/dashboards/share-dashboards-panels/)) |
| **Looker Studio** | free | Quick shareable report | Self-hosted Postgres needs a connector |
| **Superset** | free | Like Metabase, more power | Heavier to run |
| **Weekly digest** | free | Owners who never open dashboards | No drill-down |

**Decision:** the portal is source-agnostic: it reads the canonical tables, so Meta, the events API, booking tools, payments and CSV imports all show up the same way, each tagged with its source. Build your own small portal for the screens that drive action (queue, pipeline, contact timeline). Use Metabase static embeds, locked to `client_id`, for analytics charts. Use Grafana only for watching your own platform. Every option reads the same SQL views.

---

## 9. Flexibility: config layers

```
CORE ENGINE  (code, same for everyone)   ingest · identity · journeys · metrics · alerts · portal
NICHE PACK   (niches/clinic.yaml)        stages · services + values · signals · SLAs · actions · new_journey_after_days
CLIENT FILE  (clients/glow.yaml)         hours · channel ids · prices · keywords · alert people · custom rules · hooks
```

---

## 10. Custom per-client logic

Use the lowest level that solves the request:

| Level | Mechanism | Example | Who builds |
|---|---|---|---|
| 1 | **Config** | Different hours, SLA, keywords, prices, stage names | You, minutes |
| 2 | **Custom rules** in the client file (safe expressions, no code) | "VIP if lifetime value > ₱50,000", "hot if asks for Dr. Cruz" | You, minutes |
| 3 | **Inbound events API**: their system calls *your* URL | POS sends "paid ₱12,000 for 0917…" | Client's dev or n8n/Zapier |
| 4 | **Outbound webhooks**: you call *their* URL | On `journey.won` push to their CRM | Client's dev |
| 5 | **Decision hook**: you ask *their* URL for a decision, with timeout + fallback | Their own lead-scoring or branch-routing service | Client's dev |
| 6 | **Adapter** in your codebase | Native integration with their booking system | You, days |
| 7 | **n8n workflow** per client | One-off: copy hot leads into their Google Sheet | You, hours |

Never run a client's code inside your server. If they need logic, they host it (level 5) or you add it as a reusable rule or adapter.

### 10.1 Inbound events API (e.g. payments)

```http
POST /api/v1/events
X-Api-Key: <per-client key>
Idempotency-Key: pos-INV-20391

{ "event_type": "payment_received",
  "contact": { "phone": "+639171234567" },        // or psid, email, journey_id
  "occurred_at": "2026-10-04T14:12:00+08:00",
  "value": 12000, "currency": "PHP",
  "props": { "invoice": "INV-20391", "branch": "Kapitolyo" } }
```

The client file maps their vocabulary to yours:

```yaml
event_mapping:
  "Paid":       payment_received
  "Arrived":    appointment_showed
  "Booked":     consult_booked
contact_match: [psid, phone, email]       # order to try
```

**PayMongo / Xendit / Stripe**: put the `journey_id` in the payment link's metadata. Their `payment.paid` webhook comes to `/webhooks/payments/{provider}`, gets verified, and turns into `payment_received` with the exact amount.

### 10.2 Outbound webhooks (you call them)

```yaml
outbound_webhooks:
  - url: https://crm.glow.ph/hooks/revobs
    events: [journey.hot, journey.stage_changed, journey.won]
    secret_env: GLOW_WEBHOOK_SECRET          # you sign the body with HMAC-SHA256
```

```json
{ "event": "journey.hot", "client_id": "glow", "journey_id": "…", "contact": {"name": "Ana", "channel": "messenger"},
  "temperature": "hot", "interest": "botox", "next_action": "Reply now: offer 2 slots", "occurred_at": "…" }
```

Retries with backoff; a dead endpoint triggers an alert to you, never blocks the pipeline.

### 10.3 Custom rules without code

Use a small, safe expression format (e.g. JSONLogic or CEL) evaluated against the journey:

```yaml
custom_rules:
  - name: vip
    if:   { ">": [ { "var": "contact.lifetime_value" }, 50000 ] }
    then: { add_tag: vip, priority: 1, notify: manager }
  - name: wants_dr_cruz
    if:   { "in": [ "dr cruz", { "var": "last_message_lower" } ] }
    then: { set_temperature: hot, assign: "dr-cruz-desk" }
```

### 10.4 Decision hook (their logic, your pipeline)

```yaml
decision_hooks:
  score: { url: https://glow.ph/score, timeout_ms: 800, fallback: rules }
```

You send the journey summary; they return `{ "temperature": "hot", "assign_to": "branch-2" }`. If they're slow or down, the rules decide.

---

## 11. Client onboarding system

| # | Stage | Duration | Output |
|---|---|---|---|
| 1 | Discovery call | 45 min | Channels, volumes, team, tools, average deal value |
| 2 | Workflow mapping workshop (section 12) | 60–90 min | Filled mapping template → client file draft |
| 3 | Access + connect | 1–3 days | Page/IG (and WhatsApp) connected; test message and reply seen end-to-end |
| 4 | **Backfill** | 1 day | Contacts and recent chats imported (section 4); past customers tagged |
| 5 | Baseline (measure only) | 1–2 weeks | "Before" numbers |
| 6 | Leak report + targets | 1 meeting | Leaks in pesos; agreed SLAs |
| 7 | Go live | 1 week | Alerts, action queue, digest, staff trained in 30 min |
| 8 | 30-day review | 1 meeting | Before/after, label accuracy, rule tuning, upsell |

**How connecting works:**
- **Now (manual, no app review):** the client adds you as a Page admin or Business Manager partner. You generate a Page token and subscribe their Page.
- **Later (self-serve):** a "Connect your Page" button using Facebook Login for Business. Needs Meta business verification and app review for `pages_messaging` and related permissions. Start this early; it takes weeks.

**Checklist:** contract + data processing agreement + consent text · Page access · client file from niche template · webhook subscribed (`messages`, `message_echoes`, `messaging_referrals`, `message_reads`) · backfill run · booking/payment capture agreed · alert group set up · heartbeat on · baseline start date recorded.

---

## 12. Translating a client's workflow into the system

Six workshop questions → config:

| Question | Becomes |
|---|---|
| "Walk me through first message to paid." | Stages |
| "How do you know someone reached that step?" | Events |
| "Where is that written down today?" | Source + capture method |
| "How fast should each step happen?" | SLAs, metrics |
| "When something is stuck, who should know?" | Alerts + recipients |
| "What's the right next move at each step?" | Next-action rules |
| "When is a returning customer a new sale?" | `new_journey_after_days` |
| "Anything special only you do?" | Custom rules / hooks (section 10) |

Filled example (clinic):

| Stage | Proof | Lives today | Capture | SLA / metric | Alert | Next action |
|---|---|---|---|---|---|---|
| Inquiry | first message | Messenger/IG | webhook | volume by source | – | – |
| Replied | first reply | inbox | echo webhook | ≤ 5 min open hours | hot 10m → desk | reply + ask date |
| Qualified | asks date/location | chat text | classifier | qualified rate | – | offer 2 slots |
| Booked | appointment | notebook/calendar | booking link or button | inquiry → booked | – | reminders |
| Showed | arrived | front desk | "Arrived" button | show rate | no-show +15m | rebook |
| Paid | payment | POS/GCash | payment webhook or events API | revenue per ad | – | rebook date |

Rule: if logging takes staff more than 10 seconds, it won't happen. Make the action the log.

---

## 13. WhatsApp and Viber

### 13.1 WhatsApp: three setups

| Setup | How staff reply | What you can track | Notes |
|---|---|---|---|
| **Coexistence** (Business app + Cloud API on one number) | WhatsApp Business phone app, as today | Customer messages, `smb_message_echoes` for phone replies, up to ~6 months `history` at onboarding, contacts sync | Onboard via Embedded Signup as a Tech Provider or through a BSP such as 360dialog ([Meta guide](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/), [360dialog](https://docs.360dialog.com/docs/resources/phone-numbers/coexistence)) |
| **Cloud API only** | A shared inbox (Chatwoot, your portal) | Everything, since every reply goes through your system; delivery/read statuses | Number moves off the phone app |
| **Personal WhatsApp** | Staff's own phone | **Nothing** | No API. Move to a business number |

Sending rules: free-form replies within the 24h customer-service window; outside it only approved templates, which are paid per message (check Meta's current WhatsApp pricing per country).

### 13.2 Viber

| Option | What it is | Tracking |
|---|---|---|
| **Viber bot** (REST Bot API) | A bot account customers chat with; webhooks for messages, subscriptions, conversation started ([Viber REST API](https://developers.viber.com/docs/api/rest-bot-api/)) | Customer messages yes. Staff replies only if they reply through your tool (no echo of a phone app) |
| **Viber Business Messages** | Phone-number messaging via official partners, mostly outbound | Delivery/read; good for reminders |
| Personal Viber | Staff's own account | Not possible |

Cost: bots created since 5 Feb 2024 pay a monthly maintenance fee (Viber lists EUR 100–115 per bot) plus chatbot-initiated messages; messages within a 24h session started by the user are not billed ([Viber bot commercial model](https://help.viber.com/hc/en-us/articles/15247629658525-Bot-commercial-model)). **Recommendation:** skip Viber for the POC. Add it per client only if their customers really live on Viber, and price it in.

---

## 14. Test it on your own Facebook Page

No app review is needed for a Page you admin while the app is in development mode; it receives messages from people with a role on the app (you).

1. Run Postgres + `uvicorn app.main:app --port 8000` (see `poc/README.md`).
2. `cloudflared tunnel --url http://localhost:8000` → copy the https URL.
3. developers.facebook.com → Create app (Business) → add **Messenger** ([quick start](https://developers.facebook.com/documentation/business-messaging/messenger-platform/getting-started/quick-start)).
4. Webhook URL `https://…/webhooks/meta`, your verify token; copy the app secret into `META_APP_SECRET`.
5. Add your Page, generate a Page token, subscribe to `messages`, `message_echoes`, `messaging_referrals`, `message_reads`.
6. Put your Page id in `poc/config/clients/<you>.yaml`.
7. Message your Page from your personal account, reply from Business Suite, see one `in` and one `out` (staff) row with the reply time.

---

## 15. Scalability and cost

Busy clinic ≈ 1,000 conversations × 8 messages = 8,000 webhooks/month. 50 clients ≈ 400k/month: one VPS and one Postgres are enough.

| Item | POC | ~10 clients | ~50 clients |
|---|---|---|---|
| VPS + Postgres | $0 (laptop) | $12–24/mo | $40–80/mo |
| Metabase OSS / Grafana OSS | $0 | $0 (self-host) | $0 |
| Meta webhooks, Send API, Graph API | $0 | $0 | $0 |
| WhatsApp templates | – | per message outside 24h window | same |
| Viber bot (only if needed) | – | ~EUR 100–115/bot/month + initiated messages | same |
| LLM for unclear leads | ~$0–5 | ~$10–20 per client/month on Claude Opus 5.5; about a quarter of that on a smaller model | linear |

Growth path: inline → queue + worker → cron alerts + cached views → monthly partitions + read replica + row-level security → self-serve SaaS with Meta app review.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| App review / business verification needed for clients' Pages | Start early; use manual partner access meanwhile |
| Only 20 messages per conversation backfillable | Use backfill for contacts and context; take the baseline from live data |
| Tokens expire / access removed | "Silent 6h" heartbeat; secrets manager |
| Personal accounts | Not trackable; onboarding moves chats to business inboxes |
| Duplicates, out-of-order webhooks | Dedupe by message id; recompute state from stored messages |
| Wrong merges of returning customers | Auto-merge only on exact id/phone/email; suggest the rest |
| Wrong labels | Explainable rules, 100-chat validation, label history |
| Health data privacy | DPA, consent, redact phone numbers before LLM, no treatment details to ad platforms |
| Client custom logic sprawl | Levels in section 10; never run client code in your server |
| Alert fatigue | Few alerts, once per wait, open hours only |

---

## 17. LLM council review

*Simulated advisor perspectives used to stress-test the plan. They are not real people.*

**🩺 Clinic owner (buyer):** "I'll pay to stop losing night inquiries and to see which ads bring patients. Don't make my staff learn a new inbox in week one. The action queue on a phone matters more to me than charts. Show me returning patients, because rebooking is where my profit is."
→ Mobile-first action queue; returning-customer view in v1; keep the Meta inbox as the reply tool.

**🔌 Meta platform engineer:** "Echoes and referrals are solid. Three traps: the Conversations API only gives the last 20 messages, so don't promise full history on Messenger. App review and business verification gate every client Page that isn't yours, so start now. Pin a Graph API version and test upgrades; fields change."
→ Backfill = contacts + recent context only. Verification on the critical path. Version pinning.

**🛠️ Data engineer:** "Split contacts from journeys now, before real data arrives. Otherwise returning customers corrupt your funnel numbers. Keep events append-only and make every metric a SQL view you can recompute. Put `client_id` and row-level security in from client #1."
→ v1 schema change (section 7) is the first coding task after the plan is agreed.

**🎨 Product designer:** "Four views, four jobs: queue, pipeline, contact, table. Use the same temperature chips and stage names everywhere. Charts belong in the weekly digest and the owner view, not on the front desk's screen."
→ Build the portal around the action queue; Metabase only for owner analytics.

**⚖️ Privacy counsel:** "Backfilling six months of WhatsApp health conversations is a big step. Get explicit consent wording, minimise what you store, set retention (e.g. delete message bodies after 12 months, keep metrics). Decision hooks send customer data to third-party URLs, so they need contracts too."
→ Retention policy and DPA template before the first backfill; hooks only to the client's own systems.

**🏗️ Agency operator:** "Custom requests will kill your margins. The levels table is right: sell config and the events API as standard, price adapters and hooks as add-ons. Skip Viber until someone pays for it."
→ Package: Standard (config + events API + digest), Plus (outbound webhooks, custom rules), Custom (adapters, hooks).

**Where they agree:** start with Messenger + IG on your own Page; split contacts/journeys early; action queue first; verification early; Viber later.
**Where they disagree:** the owner wants the AI responder soon; the privacy counsel and Meta engineer want measurement to be stable first. Suggested middle: AI responder in phase 2, after 2 weeks of clean baseline data.

---

## 18. Roadmap and decisions

| Week | Goal | Done when |
|---|---|---|
| 0 ✓ | Engine, simulator, sample dashboard | Runs on simulated data |
| 1 | Your Page live + profile names | Real message + reply in Postgres with correct reply time |
| 2 | Contacts/journeys split + backfill job | Returning customer test passes on your Page |
| 3 | Events API + Telegram "Booked/Arrived/Paid" buttons | Booking and payment events from a phone |
| 4 | Portal v1: action queue + contact timeline | Usable on a phone |
| 5 | Alerts + weekly digest; classifier validation | 100 labelled chats measured |
| 6+ | First design-partner client; start Meta business verification in week 1 | Baseline running on a real business |

### Decisions made

| # | Decision | What it means for the build |
|---|---|---|
| 1 | **Inbox: connect clients' Meta inbox directly** (recommended option) | Staff keep replying in Meta Business Suite / the WhatsApp Business app. No Chatwoot in the POC; its adapter stays in the code for later |
| 2 | **Client dashboard covers all sources, not just Meta** | The portal reads only the canonical tables (contacts, journeys, messages, events). Every source is an adapter that writes those tables: Meta, the events API, booking tools, payments, CSV/Sheets. Each row keeps a `source` column so the dashboard can filter and show "where this came from". Meta is one adapter among many |
| 3 | **First niche: clinics** | Build and validate `clinic.yaml` first; solar and real estate packs wait |
| 4 | **Booking capture: use the clinic's existing tool when possible** | Order of preference below |
| 5 | Meta business verification timing | Open. Recommendation: start in week 1, because it gates connecting any client Page other than yours |

**Booking capture, in order of preference:**

| Clinic uses today | How we capture bookings | Effort |
|---|---|---|
| A booking tool with webhooks (Calendly, Cal.com, Acuity, many clinic systems) | Adapter: their `booking.created / cancelled / rescheduled` webhook → `consult_booked` etc. | 1–2 days per tool |
| Google Calendar | Calendar API watch/poll; match the event to a contact by phone or a `#J123` code in the title | 2–3 days |
| A clinic system with no API | Nightly CSV export upload, matched by phone | 1 day |
| Notebook / nothing | Offer our own booking link (self-hosted Cal.com, free) **or** a Telegram "Booked" button for staff | Hours |

**Remaining choices (smaller):**
1. Portal tech: server-rendered FastAPI + HTMX (simplest, recommended) or Next.js?
2. `new_journey_after_days` for clinics: 45 days?
3. Which custom levels (section 10) to sell as standard vs add-on?

---

## 19. References

Meta / Messenger / Instagram
- Webhooks for Messenger Platform: https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks
- `messages` webhook event: https://developers.facebook.com/docs/messenger-platform/reference/webhook-events/messages/
- Quick start: https://developers.facebook.com/documentation/business-messaging/messenger-platform/getting-started/quick-start
- Conversations API (history, 20-message limit): https://developers.facebook.com/docs/messenger-platform/conversations/
- Send messages: https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages
- Messenger & IG messaging policy (24h window, tags): https://developers.facebook.com/documentation/business-messaging/messenger-platform/policy
- Instagram messaging: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/messaging-api/
- Lead Ads retrieval: https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving
- Lead Ads webhooks: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen/

WhatsApp
- Onboard WhatsApp Business app users (Coexistence): https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/
- 360dialog coexistence webhooks (history, smb_message_echoes, smb_app_state_sync): https://docs.360dialog.com/partner/onboarding/whatsapp-coexistence/coexistence-webhooks

Viber
- REST Bot API: https://developers.viber.com/docs/api/rest-bot-api/
- Bot commercial model: https://help.viber.com/hc/en-us/articles/15247629658525-Bot-commercial-model

Dashboards / inbox
- Metabase securing embeds: https://www.metabase.com/docs/latest/embedding/securing-embeds
- Grafana sharing dashboards and panels: https://grafana.com/docs/grafana/latest/dashboards/share-dashboards-panels/
- Chatwoot webhooks API: https://developers.chatwoot.com/api-reference/webhooks/add-a-webhook

Some Meta pages couldn't be opened directly from this environment; the facts above come from Meta's documentation as quoted in search results. Re-check field names against the Graph API version you pin.
