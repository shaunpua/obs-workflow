# Revenue Observability: POC Plan

Status: **plan for review**. A first version of the code exists in `poc/`, but building is paused until this plan is agreed.

---

## 1. The idea in one paragraph

A business (clinic, solar installer, broker) talks to customers through a Facebook Page, Instagram or WhatsApp. Meta can send **your server** a copy of every customer message *and* every reply the business sends, even replies staff type by hand in the inbox. From those two timestamps you get speed-to-reply. From the message text you get a hot/warm/cold label. From bookings and payments you get the funnel. You store everything as an event log, so you can show each lead's journey as a trace, find where leads drop off, alert staff when a hot lead is waiting, and tell them what to do next.

## 2. How a client actually uses the service

```
Customer messages the client's Page/WhatsApp
      │
      ▼
Meta sends a webhook (HTTP POST) to YOUR app      ← the client changes nothing about how they work
      │
      ▼
Your app: store → identify lead → update metrics → label hot/warm/cold → pick next action
      │
      ├──► Front desk gets a Telegram/Viber alert: "HOT lead waiting 10 min: Ana, botox"
      ├──► Owner gets a weekly digest: "Median reply 7h → 10m, 12 consults booked (was 7)"
      └──► Dashboard: KPIs, funnel, lead list with next actions, lead traces
```

What the client does:
1. Gives you admin/partner access to their Page (and WhatsApp number later).
2. Keeps replying from the same inbox they use today.
3. Taps a button or uses a booking link when a lead books, shows up or pays. Later this comes automatically from their booking or payment tool.
4. Acts on alerts and the action queue.

---

## 3. Architecture

### 3.1 Layers

```
┌────────────────────────────────────────────────────────────────────┐
│ SOURCES        Messenger · Instagram · WhatsApp · booking · payments│
└──────────┬─────────────────────────────────────────────────────────┘
           │ webhooks (push)          API calls (pull, e.g. ad spend)
┌──────────▼─────────────────────────────────────────────────────────┐
│ INGEST         /webhooks/meta  → verify signature → store raw        │
│                normalize each platform into ONE message shape        │
└──────────┬─────────────────────────────────────────────────────────┘
┌──────────▼─────────────────────────────────────────────────────────┐
│ CORE ENGINE    lead DB · message log · event log (traces)           │
│ (same code     classifier (rules + optional LLM) · stage tracker    │
│  for everyone) next-action rules · alert checks                      │
└──────────┬─────────────────────────────────────────────────────────┘
           │ reads config: niche pack + client file
┌──────────▼─────────────────────────────────────────────────────────┐
│ METRICS        SQL views: reply time p50/p90, business-hours time,  │
│                funnel, time-in-stage, source → revenue              │
└──────────┬─────────────────────────────────────────────────────────┘
┌──────────▼─────────────────────────────────────────────────────────┐
│ OUTPUTS        Alerts (Telegram/Viber) · weekly digest · dashboard   │
│                · action queue · later: AI replies, nurture sequences │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 POC components (what's in `poc/`)

| Component | File | Job |
|---|---|---|
| Webhook receiver | `app/main.py` | Verifies Meta's signature, stores the raw body, processes it |
| Adapters | `app/normalize.py` | Messenger, Instagram, WhatsApp (incl. Coexistence echoes) and Chatwoot → one shape |
| Pipeline | `app/pipeline.py` | Lead upsert, message log, events, stage, next action |
| Classifier | `app/classify.py` | Weighted keyword rules, plus an optional Claude call for unclear cases |
| Alerts | `app/alerts.py` | Hot lead unanswered, escalation, "integration silent" |
| Schema | `db/001_schema.sql` | clients, channels, raw_webhooks, leads, messages, events, lead_labels, alerts |
| Metrics | `db/002_metrics.sql` | Business-hours function, reply-pair view, daily KPI view |
| Config | `config/niches/*.yaml`, `config/clients/*.yaml` | Everything niche- or client-specific |
| Simulator | `scripts/simulate.py` | 14 days of realistic Taglish clinic chats, sent as signed Meta webhooks |
| Dashboard | `scripts/build_dashboard.py` + `dashboard/template.html` | One HTML file built from the SQL views |

Stack: Python (FastAPI) + Postgres. You could do the same in n8n, but code is easier to version, test and reuse across clients. n8n stays useful for one-off client automations.

### 3.3 Data model (the important tables)

| Table | One row per | Why it matters |
|---|---|---|
| `leads` | person per client | **The lead database**: stage, temperature, interest, est. value, next action |
| `messages` | message, both directions | The logs. Reply times are computed from here |
| `events` | thing that happened (lead_created, first_reply, consult_booked, payment_received, alert_fired…) | The traces. Append-only, so you can always replay history |
| `raw_webhooks` | webhook body as received | Re-process when your parsing changes |
| `lead_labels` | classification change | Audit trail, and how you'll measure classifier accuracy |

---

## 4. Sample flows (what happens, step by step)

### Flow A: customer messages at night, staff replies next morning

| Time | What happens | What your system records |
|---|---|---|
| 21:14:05 | Ana: "Hi! Magkano po botox?" (clicked the Botox ad) | Meta `messages` webhook → lead created, source = `AD_BOTOX_OCT`, label **warm** (price question + interest), waiting since 21:14 |
| 21:15:10 | Ana: "Available po ba bukas? Pa-book sana" | Same wait (clock still starts at 21:14). Score jumps → **hot**, intent `ready_to_book`, event `lead_qualified` |
| 09:00 | Clinic opens | Alert check: hot + waited 10 business minutes → Telegram to front desk: *"HOT lead waiting: Ana (botox). Reply now: offer 2 slots"* |
| 09:12:40 | Staff replies in Business Suite | Meta `message_echoes` webhook (app_id = Meta inbox, so actor = staff). First reply = **11h 58m raw, 12m business-hours**. Alert resolved |
| 09:20 | Ana books 4pm via booking link | `consult_booked` event → stage **booked**, next action "Send reminder 24h and 2h before" |
| next day | Ana shows up, pays ₱15,000 | `appointment_showed`, `payment_received` → stage **paid**, revenue attributed to `AD_BOTOX_OCT` |

### Flow B: the same lead, with the after-hours AI on

21:14 message → your AI replies at 21:15 through the Send API. Meta echoes it back with **your** app_id, so actor = `ai`. First reply = 1 minute. The AI asks for a preferred date and offers slots. Staff only step in for the booking. In the simulation this took the median first reply from **7h 25m to 10m** and bookings from **7 to 12** over the same number of days.

### Flow C: a price shopper goes cold

"hm po filler" → staff reply 3h later with the price → customer says "ok po thanks" → no further messages. Rules see `price_only`, nothing else, so the lead is **cold**. After 3 quiet days it stays cold, and the next action is "Add to monthly promo list". The trace shows exactly where the conversation died: right after the price was sent without a booking ask.

---

## 5. What you get out of it

### 5.1 Metrics (with exact definitions)

| Metric | Definition | Why |
|---|---|---|
| First response time (FRT) | First business reply − first customer message | Predicts conversion more than anything else |
| Response time (every turn) | Business reply − **first unanswered** customer message in that block | 3 customer messages in a row = 1 wait, not 3 |
| Business-hours FRT | Same, counting only open hours | Judges staff fairly |
| Raw FRT | Same, wall-clock | Shows the after-hours leak (the AI pitch) |
| p50 / p90 | Median and worst-10% | Averages hide the 3-day gaps |
| Unanswered rate | Conversations with no business reply | Pure lost money |
| AI vs staff share | Replies by actor, from the echo's `app_id` | Shows what the AI is doing |
| Stage conversion | Leads reaching each stage ÷ previous stage | Funnel |
| Time in step | Median/p90 time between stages | Bottlenecks |
| Source → revenue | Ad id on first message → payments | Which ads make money, not just messages |

### 5.2 Classification (hot / warm / cold)

1. **Rules first** (free, instant, explainable). Each niche has weighted signals, e.g. clinic: `asks_to_book +45`, `asks_availability +35`, `asks_location +20`, `price_only +8`, `not_now −25`, `gone_cold −40`. Score ≥ 50 = hot, ≥ 20 = warm.
2. **Decay**: no customer message for 3 days drops a lead one level (booked or paid customers are exempt).
3. **LLM only for unclear cases** (score in the warm band). Claude returns structured JSON: temperature, intent, interest, budget, timeline, objection, next_action, confidence. Phone numbers are redacted first.
4. **Validate**: hand-label 100 real conversations, compare, fix rules. Every label change is kept in `lead_labels`.

### 5.3 Traces and bottlenecks

- **Trace** = one lead's messages + events on one timeline, each with "+time since previous step". Gaps over the SLA show in red. It reads like a request trace in observability tools: inquiry → +7h 25m → staff reply → +3m → customer → … → booked → paid.
- **Bottleneck view** = the funnel with % kept per stage plus median/p90 time per step. The step with the biggest drop is flagged. Typical findings: "Replied → Qualified keeps only 40%" (price sent without a booking ask), or "Booked → Showed keeps 47%" (no reminders).
- **Hour-of-day chart** = when inquiries arrive vs when the clinic is open. Usually 40–60% arrive after closing.

### 5.4 Actionable items

Ordered rules in the niche file; the first match wins. Examples (clinic):

| When | Action | Priority |
|---|---|---|
| Waiting for reply + hot | Reply now: confirm treatment, offer 2 slots | P1 |
| Hot + qualified, not booked | Close it today: send 2 slots + booking link | P1 |
| Waiting 48h+ | Never answered: apologise, re-offer | P2 |
| Qualified, quiet 24h | Follow up with booking link + promo | P2 |
| Booked | Send reminder 24h and 2h before | P3 |
| Showed | Ask for payment/package, set rebook date | P2 |
| Cold | Add to monthly promo list | P4 |

### 5.5 Alerts

| Alert | Rule | Goes to |
|---|---|---|
| Hot lead unanswered | Hot + waited ≥ 10 business minutes | Front desk |
| Escalation | Any lead waited ≥ 30 business minutes | Manager |
| Integration silent | No messages for 6h during open hours | **You** (usually an expired token) |

Each alert fires once per wait and auto-resolves when someone replies. Keep alerts few and actionable, or staff will mute them.

### 5.6 Lead database and nurturing

The `leads` table **is** the lead DB: every person, their stage, label, interest, estimated value and next action. Nurturing is phase 2:
- **Lists**: cold → monthly promo, warm → weekly value content, no-show → rebook sequence, paid → rebook reminder at the treatment's cycle (e.g. Botox ~4 months).
- **Platform rules matter**: Messenger allows free-form replies within 24h of the customer's last message. Outside that window you need approved message tags (Messenger) or paid templates (WhatsApp). Design sequences around the window, e.g. send the follow-up while it's still open.

---

## 6. Showing data to the client: build or reuse?

| Option | Cost | Good for | Weak at |
|---|---|---|---|
| **Weekly digest** (Telegram/Viber/WhatsApp/email) | Free | Owners, who rarely open dashboards | Drill-down |
| **Metabase** (open source, self-host) | Free + small VPS | Fast owner dashboards on your SQL views, per-client permissions, scheduled emails | Custom visuals such as trace timelines |
| **Grafana** | Free | Ops: time series, alert rules, you already know it | Business users find it technical |
| **Looker Studio** | Free (Google) | Quick shareable reports | Self-hosted Postgres needs a connector, slower |
| **Apache Superset** | Free | Like Metabase, more power, more setup | Heavier to run |
| **Custom page** (like `poc/dashboard`) | Your time | Action queue, traces, branded client portal, the future SaaS | You maintain it |

**Recommendation:**
- **POC**: the generated HTML page (already built) plus a weekly digest message.
- **First paying clients**: Metabase on the same SQL views for KPIs and funnels, plus the custom page for the action queue and traces. Metabase's free tier has no per-client row filtering, so give each client their own collection with filtered questions, or run one Metabase per client at first.
- **Later (SaaS)**: one custom portal with login per client.

The rule that keeps this cheap: **all dashboards read the same SQL views**, so changing tools never means rewriting metrics.

---

## 7. Flexibility: one engine, many niches, light per-client tweaks

Three layers, from rarely changed to often changed:

```
1. CORE ENGINE  (code, same for everyone)
   ingest · normalize · lead DB · events · reply-time math · alerts · dashboards

2. NICHE PACK   (config/niches/clinic.yaml, solar.yaml, realestate.yaml)
   stages · interests + typical values · classification signals · SLAs · next-action rules

3. CLIENT FILE  (config/clients/<client>.yaml)
   business hours · channel ids · stage renames · extra keywords · price overrides · alert recipients
```

The client file is deep-merged over the niche pack. Example of what one client changes:

```yaml
client_id: glow-aesthetics
niche: clinic
business_hours: { open: "09:00", close: "20:00", days: [1,2,3,4,5,6] }
channels:
  messenger: { external_id: "1234567890" }
overrides:
  sla: { hot_unanswered_alert_minutes: 10 }
  interests:
    botox: { value: 15000 }                         # they charge more
    skin_booster: { keywords: ["rejuran"], value: 18000 }   # a service only they offer
```

**What counts as a "customisation" vs new work:**
- Config only (minutes): hours, SLAs, keywords, prices, stage names, alert recipients, action wording.
- New adapter (days): a new source, e.g. their booking system, POS or Google Sheet.
- New niche pack (1–2 weeks with a real client): new stages, signals and actions.
- Custom code: avoid. If two clients need it, it belongs in the engine.

---

## 8. Client onboarding system

### 8.1 Stages

| # | Stage | Duration | Output |
|---|---|---|---|
| 1 | Discovery call | 45 min | Channels, volumes, team, tools, average deal value, pain points |
| 2 | **Workflow mapping workshop** | 60–90 min | Filled mapping template (section 9) |
| 3 | Access + connect | 1–3 days | Page/IG/WA connected, channel ids in the client file, test message seen end-to-end |
| 4 | Baseline (measure only) | 1–2 weeks | "Before" numbers: FRT, unanswered rate, after-hours share, funnel |
| 5 | Leak report + targets | 1 meeting | Leaks in pesos and agreed SLAs (e.g. 95% answered within 5 min in open hours) |
| 6 | Go live | 1 week | Alerts on, action queue in use, digest scheduled, staff trained (30 min) |
| 7 | 30-day review | 1 meeting | Before/after, label accuracy check, rule tuning, upsell (AI responder, nurture) |

### 8.2 Onboarding checklist (per client)

- [ ] Contract, data processing agreement, consent text for chat
- [ ] Page admin / Business Manager partner access granted
- [ ] `config/clients/<id>.yaml` created from the niche template
- [ ] Webhook subscribed (`messages`, `message_echoes`), test inbound + reply verified
- [ ] Booking/payment capture decided (link, button, or integration)
- [ ] Alert recipients joined the Telegram/Viber group
- [ ] Heartbeat alert on for this client
- [ ] Baseline start date recorded

---

## 9. Translating a client's workflow into the system

This is the core consulting skill. You turn "how they sell" into **stages → events → sources → metrics → alerts → actions**. Do it as a workshop with the owner and the person who answers the inbox.

### 9.1 The six questions

1. **Journey**: "Walk me through what happens from the first message to getting paid." → **stages**
2. **Proof**: "How do you know someone reached that step?" → **events** (and which tool records them)
3. **Where it lives**: "Where is that written down today?" → **source + capture method**
4. **Good looks like**: "How fast should each step happen?" → **SLAs / metrics**
5. **Who acts**: "When something is stuck, who should know?" → **alerts + recipients**
6. **What to do**: "What's the right next move at each step?" → **next-action rules**

### 9.2 Mapping template (worked example: clinic)

| Stage | Proof (event) | Where it lives today | How we capture it | SLA / metric | Alert → who | Next action |
|---|---|---|---|---|---|---|
| Inquiry | first message | Messenger/IG inbox | Meta webhook (automatic) | Volume by source | — | — |
| Replied | first business reply | Inbox | `message_echoes` (automatic) | FRT ≤ 5 min open hours | Hot waiting 10m → front desk | Reply + ask date |
| Qualified | asks date/slot/location | Chat text | Classifier (automatic) | Qualified rate | — | Offer 2 slots |
| Booked | appointment made | Notebook / Google Calendar | Booking link (Cal.com) or staff button | Inquiry → booked % | — | Reminders |
| Showed | arrived | Front desk | Staff "Arrived" button | Show rate | No-show +15m → front desk | Rebook sequence |
| Paid | payment | POS / GCash | Payment link webhook or staff button | Revenue per lead, per ad | — | Rebook date |

### 9.3 Where data usually lives, and how to capture it

| Data | Usually lives in | Capture (best → fallback) |
|---|---|---|
| Messages + replies | Meta inbox, WA Business app | Webhooks (automatic). Personal accounts can't be tracked, so move them to the business inbox |
| Bookings | Notebook, Google Calendar, booking app | Booking-link webhook → Google Calendar API → staff button |
| Show-ups | Front desk memory | Staff one-tap button (Telegram bot or simple form) |
| Payments | POS, GCash, bank transfer | Payment-link webhook → daily CSV upload → staff button |
| Ad spend | Ads Manager | Marketing API pull (daily) |
| Lost reason | Nowhere | Classifier on chat text, plus an optional staff tag |

Rule: **if logging takes staff more than 10 seconds, it won't happen.** Make the action itself the log, e.g. sending a booking link creates the booking event.

### 9.4 Same method, another niche (solar, quick view)

Inquiry → Replied → **Bill received** (photo in chat = qualified) → Proposal sent → Site survey → Contract signed. SLA: bill → proposal ≤ 24h. Alert: proposal with no follow-up in 3 days → sales. Only a new `solar.yaml` is needed (it already exists in `poc/config/niches/`).

---

## 10. Test it yourself with your own Facebook Page

You don't need app review: in development mode a Meta app works for Pages you admin, with messages from people who have a role on the app.

1. **Run the kit locally**: Postgres + `uvicorn app.main:app --port 8000` (see `poc/README.md`).
2. **Public URL**: `cloudflared tunnel --url http://localhost:8000` (or ngrok) → gives `https://xxxx.trycloudflare.com`.
3. **Meta app**: developers.facebook.com → Create app → type *Business* → add the **Messenger** product.
4. **Webhook**: callback URL `https://xxxx.trycloudflare.com/webhooks/meta`, verify token = your `META_VERIFY_TOKEN`. Set `META_APP_SECRET` from App settings → Basic.
5. **Page**: in Messenger settings, add your Page, generate a Page access token, and subscribe the Page to the `messages` and `message_echoes` fields.
6. **Put your Page id** in `poc/config/clients/<you>.yaml` under `channels.messenger.external_id`.
7. **Test**: message your Page from your personal account (you're an app admin). Reply from Meta Business Suite. Watch two rows appear in `messages`: one `in`, one `out` with actor `staff`.
8. **See it**: `python -m scripts.build_dashboard --client <you> --standalone`.

Notes: Messenger webhooks give an id, not a name. Fetching the name needs a Graph API call (not in the POC yet). Instagram works the same way once the IG account is linked to the Page. WhatsApp needs a Business number and is a later step.

---

## 11. Scalability and cost

### 11.1 Volume reality check

A busy clinic: ~1,000 conversations/month × ~8 messages = **8,000 webhooks/month** (≈ 1 every 5 minutes). 50 clients ≈ 400k/month. One small server and one Postgres handle that comfortably.

### 11.2 Your monthly cost (rough)

| Item | POC | ~10 clients | ~50 clients |
|---|---|---|---|
| Server (app + Postgres) | $0 (laptop) | $12–24 VPS | $40–80 (bigger VPS or managed DB) |
| Metabase | — | $0 self-host (needs ~2GB RAM) | $0 self-host |
| Tunnel / domain | $0 | ~$1 domain | ~$1 |
| Meta webhooks + Send API | $0 | $0 | $0 |
| WhatsApp | — | Replies within the 24h service window are free. Template messages are paid per message, so check Meta's current rates | same |
| LLM labels (optional) | ~$0–5 | ~$5–20 per client | scales linearly |

LLM estimate: ~1,000 conversations × ~30% unclear × ~3 calls ≈ 900 calls/month per client. At roughly 1–2 US cents per call with Claude Opus 5.5 that's about $10–20 per client per month. A smaller model (e.g. Claude Haiku 4.5) costs about a quarter of that, so test both on your 100 labelled conversations. Rules handle most leads for free.

### 11.3 What to change as you grow

| When | Change |
|---|---|
| Now (POC) | Process webhooks inline |
| First real clients | Return 200 immediately, put the raw id on a queue (Postgres `LISTEN/NOTIFY` or Redis), process in a worker |
| ~10+ clients | Run alert checks as one cron job; add a dashboard cache (materialized views refreshed every 5 min) |
| ~50+ clients | Partition `messages`/`events` by month; read replica for dashboards; Postgres row-level security per client |
| SaaS | Login per client, self-serve "connect your Page" flow (needs Meta app review + business verification) |

---

## 12. Risks and known issues

| Risk | Mitigation |
|---|---|
| **Meta app review** needed for clients' Pages | Start now: business verification + `pages_messaging` review take weeks. Your own Page works without it |
| Tokens expire / staff remove access | "Integration silent" alert; store tokens in a secrets manager |
| Staff reply from **personal** accounts | Invisible by design. Onboarding moves chats to the business inbox |
| Webhook retries → duplicates | Dedupe by message id (already in place) |
| Out-of-order delivery | Lead state is recomputed from the message table, not from arrival order (already in place) |
| Classifier wrong | Rules are explainable; validate on 100 hand-labelled chats; keep label history |
| Privacy (health data for clinics) | DPA, consent text, redact phone numbers before any LLM call, store only what you need, never send treatment details to ad platforms |
| Bookings/payments not captured | Without them you only see the top of the funnel. Agree on a capture method in the mapping workshop |
| Alert fatigue | Few alerts, each fires once per wait, business hours only |
| Messaging window rules | Design nurture inside the 24h window or with approved templates/tags |

---

## 13. POC roadmap

| Week | Goal | Done when |
|---|---|---|
| 0 (done) | Engine + simulator + sample dashboard | `poc/` runs on simulated data |
| 1 | **Your own Page live** | A real message and your reply land in Postgres with the right reply time |
| 2 | Booking/payment capture | Telegram "Booked / Arrived / Paid" buttons create events |
| 3 | Alerts to your phone + weekly digest | You get a Telegram ping for a test hot lead |
| 4 | Classifier validation | 100 labelled chats, accuracy measured, rules tuned |
| 5–6 | First design-partner client | Baseline running on a real business |

## 14. Decisions for you

1. **Inbox strategy**: connect clients' existing Meta inbox directly (recommended for the POC), or put Chatwoot in front?
2. **Dashboard for first clients**: Metabase + custom action page (recommended), or custom only?
3. **First niche**: clinic (fastest proof) or another niche you have access to?
4. **Booking capture**: booking link, staff button, or their existing tool?
5. **When to start Meta business verification** (it gates onboarding real clients).
