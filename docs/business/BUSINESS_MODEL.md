# Business model (DRAFT)

What we sell, in what order, and what we deliberately don't sell yet. Draft: edit as discovery calls teach us more.
Sales approach notes come from the "first $10K client" webinar (`reference/first-10k-client-webinar.txt`); the points that apply to us are in section 5.

## 1. The one-line offer

> **"You'll stop losing Messenger inquiries, and you'll see in pesos what slow replies were costing you."**

Say what changes, not what we build. Not "webhooks, dashboards, lead scoring".

## 2. The building blocks, and when each is sold

| Block | What the client gets | Sell when | Why then |
|---|---|---|---|
| **Observability** (reply times, missed/late leads, leak report) | Proof of where money leaks | **Now: the core** | Measurable, no behaviour change for staff, our unique part |
| **Lead database** (every inquiry, name, history, returning guests) | A list they never had | Now, bundled | Comes free with observability; don't price it separately |
| **Alerts + action queue** (hot lead waiting 10 min → ping) | Fewer lost leads | Now, bundled | Turns the numbers into a habit; this is the retention driver |
| **Workflow agent** (rules on pipeline events: follow-ups, tasks, hand-offs, AI replies after hours) | Work done for them | Phase 2 upsell, after 2 weeks of baseline | Needs clean data first, or we can't prove it helped |
| **Collectors deeper in the funnel** (booking tool, payments, website form/UTM) | Revenue per lead, ad ROI | Per client, when they ask "which leads paid?" | Each is an adapter; build only for a paying client's tool |
| **Lead reactivation** (follow up old leads from the database) | Revenue from leads they already paid for | Phase 2-3 | Highest-ROI "lead gen" and it uses our data (see section 3) |
| **New-lead generation** (ads, outbound) | More inquiries | Not now | See section 3 |

## 3. Lead generation: my recommendation

**Don't sell new-lead generation yet.** Reasons:
- It is a different business (ads buying, creatives, outbound) and a crowded one; we'd compete on price.
- Pouring more leads into a business that answers in 3 hours wastes their ad money. Our pitch is the opposite: fix the leak first.
- "AI lead gen" usually means scraped lists + automated cold messages: low trust, spam risk, and Philippine Data Privacy Act exposure. Meta also limits messaging people outside the 24-hour window.

**What to sell instead, in order:**
1. **Leak fix** (observability + alerts): more bookings from the same leads.
2. **Reactivation**: past inquiries in the lead database who never booked get a follow-up (by staff from the queue first; automated later within Meta's rules: 24h window, message tags, or WhatsApp templates).
3. **Ad attribution**: click-to-Messenger ads carry the ad id on the first message; we can show which ad produced bookings. Partner with an ads person rather than running ads ourselves.

When a client asks for more leads, the answer is "let's first make sure you convert the ones you already pay for, and we'll show you which ads work."

## 4. My view of the idea

**Good:**
- A real, measurable pain (slow replies lose bookings) that owners already feel.
- Meta's echo webhooks let us measure without changing how staff work. That is rare and is our technical edge.
- We have case study #1 in-house: BackHome Short Term Rentals. Run it for 2-4 weeks and get real numbers.
- Service first, productize later fits the stage we're in.

**Risks to manage:**
- **Too many blocks at once** splits focus. Sell one outcome (the leak fix); everything else is an upsell.
- **Meta dependency:** app review + business verification are needed before any non-tester client Page. Start it early. This is the critical path.
- **Proof before scale:** no case study yet. The first 2-3 clients should be warm network, priced as paid pilots.
- **Custom requests** eat margin. Keep the tiers in `../POC_PLAN.md` §17 (Standard / Plus / Custom).

**Missing ideas worth adding later:**
- Weekly digest to the owner (the thing they actually read).
- Staff scorecard (reply time per person), only if the client wants it; sensitive.
- After-stay review request (stage `review_left` already exists in the short-stay pack).
- Missed-call capture (Messenger/WhatsApp calls are subscribable; regular phone calls need a separate call-tracking tool).

## 5. How we sell (from the webinar, what applies to us)

- **Pitch first, build after payment.** The POC is enough to demo; don't build M3-M6 before someone pays.
- **Target a person, not an industry.** Start with owners we know: short-stay hosts (BackHome network, PocketHost users), clinics, and local service businesses in our city.
- **Warm circle first** (contacts, ex-coworkers, the hosts we already know), then the city: chamber of commerce, BNI, host and clinic owner groups. Cold email last.
- **Free audit as the door opener:** "Give us Page access for 2 weeks; we'll show you how many inquiries waited over an hour and what that's worth." The leak report is the proof and the price anchor.
- **Price on value, not hours.** Setup fee (audit + onboarding) + monthly retainer. Never discount; reduce scope or split payments instead.
- **Ask for referrals** right after the first win.
- **Record calls** (with permission) and review them.

## 6. Pricing shape (numbers to validate in discovery)

| Item | What | How to set it |
|---|---|---|
| Audit / pilot | 2-week baseline + leak report | Paid, small, credited to setup if they continue |
| Setup | Connect channels, client config, alert group, staff briefing | One-time; scales with channels and adapters |
| Monthly retainer | Monitoring, alerts, digest, monthly review, rule tuning | A fraction of the monthly leak we measured |
| Add-ons | Workflow agent, booking/payment adapter, reactivation campaigns | Per item |

## 7. Next 90 days (business side)

1. Run BackHome for 2-4 weeks → case study with numbers.
2. Write the warm list: hosts, clinic owners, local businesses that sell over Messenger. Tag owners vs connectors.
3. 10 conversations → 2-3 paid pilots (audit offer).
4. Start Meta business verification + app review in parallel (gates clients' Pages).
5. After 2 pilots: fix the price and package; then attend a chamber or BNI meeting with the case study.
