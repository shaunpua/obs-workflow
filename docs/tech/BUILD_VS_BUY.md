# Build vs Buy

What we make ourselves and what we take from existing tools, so we don't reinvent the wheel.

**Rule:** build only what makes the service different. Use existing tools for everything else.

What makes us different (what we build):
1. **One data model for every source**: contacts, journeys, messages, events. Adapters write into it.
2. **Identity and journey logic**: same person across channels; returning customers.
3. **Metric definitions**: reply time from the first unanswered message, business hours, funnel and step times, as SQL views.
4. **Lead labelling and next-action rules**, packaged per niche (`clinic.yaml`).
5. **The action screens** clinics use daily: action queue, pipeline, contact profile with trace.
6. **The onboarding playbook**: workflow mapping, leak report, baseline.

---

## 1. Charts and custom panels: who makes them?

| Need | Who / what | How |
|---|---|---|
| Fixed screens every clinic gets (queue, pipeline, contact trace, overview) | **We build**, once, for all clients | Our app (FastAPI + HTMX). Charts drawn with **Apache ECharts** (a free chart library): we pass it data, it draws the chart. We don't hand-draw charts |
| A clinic asks for a new chart ("bookings by doctor per week") | **Metabase** (tool), made by us in its UI | Write a SQL question or use the point-and-click editor, save it to the clinic's dashboard. Minutes, no code, no deploy |
| Owner wants to explore data themselves | **Metabase** login for that clinic | Each clinic sees only its own data (see 1.1) |
| Show a Metabase chart inside our app | Metabase **static embed** (free) | Signed iframe locked to `client_id`. Shows a small "Powered by Metabase" badge |
| Watching our own servers, webhooks, queue | **Grafana + Prometheus** (tools) | Internal only; clients never see it |

All metrics live once in Postgres as SQL views. Our screens and Metabase both read those same views, so a number is the same everywhere.

### 1.1 Keeping clinics' data separate in free Metabase

Free (open-source) Metabase has no per-row permissions. Workaround that costs nothing:
- Create a Postgres login per clinic (e.g. `mb_glow`) and turn on Postgres row-level security so that login only sees rows with its `client_id`.
- In Metabase, add one "database connection" per clinic using that login, plus one collection per clinic.
- The clinic's Metabase group can only use its own connection and collection.

If we outgrow this, Metabase Pro adds proper row-level permissions and white-labelling.

---

## 2. Product: build vs buy

| Area | We build | We use (tool) | Notes |
|---|---|---|---|
| Staff inbox (where staff reply) | – | **Meta Business Suite, WhatsApp Business app**; later **Chatwoot** | Never build an inbox |
| Receiving messages | Thin webhook endpoints + adapters | **Meta Messenger / Instagram / WhatsApp APIs** | Adapters are small: one file per platform |
| Names, history, ad spend | Small pull jobs | **Graph API, Conversations API, Marketing API** | |
| Data store | Schema + views | **Postgres** | |
| Job queue | – | **Postgres `SKIP LOCKED`** or **Procrastinate** (library) | No Kafka, no RabbitMQ |
| Scheduled jobs | Job functions | **APScheduler** or cron | |
| Identity and journeys | **Yes, core** | – | Our logic |
| Metric definitions | **Yes, core** (SQL views) | Optional **dbt** later for testing views | |
| Lead labelling | Rules + niche packs | **Claude API** for unclear cases | |
| Custom per-client rules | Rule config format | **json-logic** library to evaluate them | Don't write our own rule language |
| Next actions | **Yes, core** | – | |
| Action screens (queue, pipeline, contact) | **Yes** | **HTMX**, **ECharts**, a CSS starter such as **Pico CSS** | Mockup is the spec |
| Ad-hoc charts and custom panels | – | **Metabase OSS** | See section 1 |
| Ops monitoring | Health metrics in the app | **Prometheus, Grafana, Uptime Kuma, Sentry** | |
| Alerts to staff | Message text + rules | **Telegram Bot API** (free); email via **Resend / Postmark / Amazon SES** | Viber bot only as paid add-on |
| Weekly digest | Template + numbers | Same Telegram / email tools | |
| Bookings | Adapter per booking tool | Clinic's own tool; **Cal.com** (self-hosted, free) if they have none | |
| Payments | Adapter per provider | **PayMongo, Xendit**, Stripe abroad | Journey id in payment-link metadata |
| One-off client automations | – | **n8n** (self-hosted) | Keeps glue out of our code |
| Sending results back to Meta ads | Small job | **Meta Conversions API** | Phase 2 |
| WhatsApp onboarding | – | A provider such as **360dialog** until we become a Meta Tech Provider | |
| Portal login | Simple shared password in the POC | Later **FastAPI-Users**, or **Clerk / Supabase Auth** | Don't build password resets ourselves |
| Hosting | Docker Compose file | VPS (e.g. **Hetzner, DigitalOcean**), **Caddy** for HTTPS | |
| Secrets | – | **Infisical** or **Doppler** | |
| Backups | – | Provider snapshots + **pgBackRest** or `pg_dump` cron | |
| Local testing of webhooks | – | **cloudflared** tunnel | |
| Demo data | Simulator (exists) | – | Our sales demo |

---

## 3. Running the service business: build vs buy

| Area | We build (once, as templates) | We use (tool) |
|---|---|---|
| Our own sales pipeline | – | **HubSpot free** or **Notion** |
| Booking sales calls | – | **Cal.com** or **Calendly** |
| Discovery questions + workflow-mapping template | **Yes** (from the plan, §11–12) | **Notion / Google Docs**; **Excalidraw / FigJam** for drawing their flow |
| Onboarding intake form | Question list | **Tally** or **Google Forms** |
| Onboarding checklist per client | **Yes** (plan §11) | **Notion** template |
| Proposal and contract | Our wording, reviewed by a lawyer | **Google Docs** + e-sign (**Documenso** free, or **Dropbox Sign / PandaDoc**) |
| Data processing agreement, consent text | Templates, reviewed by a PH lawyer | – |
| Leak report / audit report | **Yes**: generated from our SQL views | Exported as PDF or shared page |
| Invoicing and retainers | – | **Xendit / PayMongo** invoices, or **Stripe Billing** abroad; **Xero / QuickBooks** for accounting |
| Client support | – | Shared **Viber / WhatsApp** group per client + **Notion** or **Linear** for tasks |
| Runbooks (what to do when an alert fires) | **Yes**, short pages | Repo `docs/` or Notion |
| Status page for clients | – | **Uptime Kuma** status page |
| Training staff | 1-page guide + 30-min call | **Loom** for short videos |

---

## 4. What changes in the POC because of this

- The **portal** stays our own app for the fixed screens (milestone M4).
- **Metabase** joins the POC as milestone **M4b**: run it in Docker, connect a read-only Postgres login, build the owner dashboard and one custom panel, and embed one chart in our overview page. This answers "can a clinic get custom panels?" without us coding charts.
- **Rules** use a json-logic library instead of our own expression parser.
- **Alerts** use Telegram first; email through a sending service, not our own mail server.
