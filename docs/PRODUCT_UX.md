# Product and UX: views, customisation, scaling

Companion to `docs/mockups/client-app.html` (clickable, fake data, light by default with a dark switch).

---

## 1. The short answer to "do I have to edit every dashboard for every client?"

No. There are three layers, and only the last one is ever "us doing it by hand":

| Layer | What it is | Who changes it | How |
|---|---|---|---|
| **1. Fixed screens** (our app) | Action queue, Journeys, Pipeline, Contacts, Activity log, Bottlenecks, Overview | Nobody per client. We improve them for everyone | Code, released to all clients at once |
| **2. Settings in our app** | Pipelines and stages, targets, alerts, tags, quick links, which treatment goes to which pipeline, saved filters | **The clinic**, in forms (no code). Or us during onboarding | "Pipelines & rules" screen |
| **3. Custom dashboards** | Extra charts, layouts, exports, scheduled reports | **The clinic's power user** (owner, marketer), or us as a paid add-on | Metabase: per-clinic collection, start from our templates, drag, resize, add panels |

Most clinics will only use layers 1 and 2. Layer 3 is for the one owner who wants "bookings by doctor per week".

---

## 2. How this compares to your Kubernetes observability platform

| | Your OTel / Kubernetes platform | This service |
|---|---|---|
| Users | Engineers | Clinic owners, front desk, marketers |
| What they want | Raw signals; they build their own views | Answers and next actions; they don't want to build anything |
| Onboarding | Install collector, give them a scoped folder + permissions | We connect sources, map their workflow, set pipelines and targets |
| Dashboards | Self-serve from day one | **Opinionated screens first**, self-serve dashboards as an extra |
| Alerts | They write alert rules | We ship sensible alerts; they adjust thresholds and recipients in forms |
| Labels | Free-form labels on metrics | Fixed core labels (hot/warm/cold, stage, pipeline, source) + their own tags |
| Tenancy | Folder per team, RBAC | Same idea: `client_id` everywhere, a Metabase collection + DB login per clinic, roles in our app |

**What we copy from your platform:** tenant isolation from day one, per-tenant folders and permissions, templates that tenants clone, self-serve alerts and dashboards for power users, and monitoring of the collectors (our "silent source" heartbeat).

**What is different:** a clinic owner will never build a dashboard from scratch. The value is in the defaults: the right screens, the right metrics and the right next action already there on day one. Self-serve is the escape hatch, not the product.

**As we scale:** layer 2 settings and layer 3 templates mean a new clinic is mostly a config, not a project. Requests that come up for 2+ clinics move into layer 1 or into a template.

---

## 3. The screens (and why each exists)

| Group | Screen | Job | Who uses it |
|---|---|---|---|
| Today | **Action queue** | Who to message now, with one-tap links to the exact chat or the clinic's system | Front desk, every hour |
| Today | **Overview** | AI summary of the week + key numbers + pipeline at a glance | Owner, weekly |
| Leads | **Journeys** | Every lead left to right, like a trace. Click a row → waterfall of steps + AI summary + next step. Click a step → details (when, how long vs target, who, source, link to the messages) | Manager, owner, us during diagnosis |
| Leads | **Pipeline** | Kanban per service line: count, potential value, median time to reach, % moved in from previous, a Lost column with reasons, late cards in red | Manager, daily |
| Leads | **Contacts** | The lead database: tags, pipeline, stage, lifetime value, export CSV | Owner, marketing |
| Leads | **Activity log** | Every message, reply, label change, booking, payment and alert as a searchable stream (our "logs") | Us and managers, for "what happened?" |
| Improve | **Bottlenecks** | AI diagnosis + funnel + lost reasons | Owner, monthly review |
| Improve | **Dashboards & reports** | Templates and custom dashboards (Metabase), export PDF, schedule email | Owner, marketing |
| Setup | **Pipelines & rules** | Stages, targets, alerts, tags, treatment → pipeline mapping, quick links | Clinic admin, us during onboarding |
| Setup | **Sources** | Connected sources and their health | Admin, us |

### 3.1 The journey view (trace for a lead)

Like a trace in Grafana Tempo/Jaeger, but the columns are **stages**, not services:
- One row = one journey. Each cell = one stage: done (green, with how long it took), slow (orange, over target), current (blue, "waiting 39m"), stopped (red ✕), not reached (dashed).
- Filters: Open / Won / Lost, "stopped at stage X" (e.g. everyone who stopped at Consult booked).
- Click a row: waterfall on a time axis (each stage a bar), an AI summary of the lead, the suggested next step.
- Click a step: when it started and ended, target, who did it (patient, staff, AI, booking tool, payment), source, and a button to open the messages of that step.

Why stages instead of a raw time waterfall only: owners think in stages ("she stopped at booking"), and the per-stage target makes "slow" visible without reading timestamps.

### 3.2 Multiple pipelines and labels

- A clinic can have **several pipelines**, one per service line (Injectables, Laser & skin packages, Body contouring). Each has its own stages, targets and alerts.
- A journey is put in a pipeline by its **treatment interest** (from the classifier), with a manual override.
- A returning patient asking about a different treatment opens a new journey in that pipeline.
- Labels on every journey: `pipeline`, `stage`, `temperature` (hot/warm/cold), `intent`, `source`, `outcome` (open/won/lost), `lost_reason`. Clinic-defined **tags** on top (VIP, Price-sensitive, Wants weekend, Rebook due), each with a rule or added by hand.

### 3.3 Actionable items and links

Every action has a button that goes straight to where the work happens:
- **Open the chat:** Messenger/Instagram conversation in Meta Business Suite; WhatsApp via `https://wa.me/{phone}`.
- **Clinic system:** a per-client URL template, e.g. `https://clinic.example.ph/patients?phone={phone}`.
- **Booking link:** per-client URL with the journey id, so the booking comes back matched.
- **Mark booked / arrived / paid:** creates the event when no integration exists.

(The exact Business Suite deep-link format must be checked during M1; if Meta doesn't support linking to one conversation, the button opens the inbox filtered to the contact.)

### 3.4 AI summaries (where and how)

| Where | What it says | Built from |
|---|---|---|
| Lead (journey detail) | 2–3 sentences: what they want, objections, preferences, where it stands + suggested next step | That journey's messages and events |
| Overview | The week in 3 sentences + 3 suggestions | Metric views + aggregated lost reasons |
| Bottlenecks | Where leads drop, the pattern behind it, what to try, expected effect | Funnel views + lost-reason counts + sample conversations |

Rules: numbers always come from SQL, never invented by the model; every AI claim links to the journeys behind it; summaries are cached and refreshed on new messages (lead) or nightly (overview, bottlenecks); phone numbers are redacted before the model sees text.

### 3.5 Exports and reports

- Contacts and any table: **CSV** (our app).
- Dashboards: **PDF / PNG** and **scheduled email** (Metabase subscriptions).
- **Monthly leak report** for the owner meeting: generated by us from the views (PDF), including before/after and the AI diagnosis. Used in monthly reviews and for case studies.

---

## 4. Handling client requests

| Request | Answer |
|---|---|
| "Rename a stage / change a target / add an alert" | They do it in Pipelines & rules. Or we do it in 2 minutes on a call |
| "Add a pipeline for dental braces" | Duplicate a pipeline, edit stages. Minutes |
| "I want a chart of X" | Metabase panel in their dashboard. 10 minutes. Free within the plan up to N per month, then paid |
| "Move/resize panels" | They do it in Metabase (drag and resize) |
| "Connect our clinic system" | Events API (their dev) or an adapter (us, paid) |
| "Our process is different" | Workflow mapping workshop → new pipeline config. If 2+ clinics need it, it goes into the product |
| "A screen that works differently" | Product backlog; we don't fork screens per client |

Rule from your own world: **no per-tenant code forks.** Config, templates and the events API cover per-client differences.

---

## 5. LLM council: recommendations

*Simulated advisor perspectives used to stress-test the design. They are not real people.*

- **Front-desk lead (daily user):** "The action queue and the Open-chat button are the only things I need. Don't make me read charts. Show 'waiting 39m' in red." → Queue is the home screen; red late timers everywhere.
- **Clinic owner:** "Give me one page on Monday: what happened, what to fix, how much it cost me. I'll look at journeys only when something looks wrong." → AI weekly summary on Overview + Monday digest; journeys for drill-down.
- **SRE (you):** "Treat a journey like a trace: stage spans, targets as SLOs, error budget for slow replies, and an event log you can grep. Don't build a query language for clinics." → Journey view + activity log; SQL stays ours, Metabase for power users.
- **Product designer:** "Several pipelines can confuse people. Default to one pipeline per clinic and add more only when a service line really behaves differently." → Start with one pipeline at onboarding; split later.
- **Data engineer:** "Lost reasons must be a fixed list per niche, not free text, or the bottleneck chart is useless. Let the AI pick from the list." → Lost reasons enumerated in `clinic.yaml`; AI chooses, staff can correct.
- **Privacy counsel:** "AI summaries of health conversations are sensitive. Keep them inside the clinic's tenant, never in exports by default, and let the clinic turn them off." → Per-client `ai_summaries: on/off`; summaries excluded from CSV unless chosen.

**Extra recommendations**
1. **Staff accountability, gently:** median reply time per staff member (and for the AI) on the Front desk dashboard template, not on the queue.
2. **Targets as SLOs:** show "95% answered within 5 min this week (target 90%)" with a simple error budget. You already know how to sell this.
3. **Saved views:** let managers save filters ("Lost at booking, last 7 days, Filler") and pin them in the sidebar. Cheap and covers many "custom dashboard" requests without Metabase.
4. **Weekly 15-minute review ritual:** the Bottlenecks page is built for this meeting. Sell the meeting, not the page.
5. **Don't build drag-and-drop in our app.** Layout editing lives in Metabase. Our screens stay fixed and fast.

---

## 6. What this changes in the POC build

Added to `docs/POC_IMPLEMENTATION.md`:
- `pipelines` and `pipeline_stages` tables (M2), with treatment → pipeline mapping from `clinic.yaml`.
- Journeys trace screen and Activity log screen in the portal (M4).
- Pipelines & rules screen: edit stages, targets, alerts, tags, quick links (M4, simple forms).
- Quick links per client (M4).
- AI lead summary + weekly summary (new M5b, behind `LLM_SUMMARIES=1`).
- Lost reasons as a fixed list per niche (M2).
- Light theme by default with a dark switch.
