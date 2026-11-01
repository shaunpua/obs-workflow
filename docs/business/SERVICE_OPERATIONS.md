# Running the service: who does what, and what we promise (DRAFT)

After onboarding ([`CLIENT_ONBOARDING.md`](CLIENT_ONBOARDING.md)), this is how a client month runs.

## Short answer to "do I just stay available for config and bug fixes?"

No. If we only fix bugs, the client sees a dashboard and stops looking at it in a month, and then cancels.
The retainer is paid for **the review and the tuning**: we read the numbers, tell them what to change, and adjust rules.
Day-to-day replying stays theirs. Watching that it happens is ours.

## Who does what

| Task | Us | Client |
|---|---|---|
| Reply to guests/customers | | ✔ (from the Page inbox only) |
| Act on alerts ("hot lead waiting 10 min") | | ✔ |
| Mark bookings/payments (button or their booking tool) | Set up | ✔ |
| Keep the data flowing (webhooks, tokens, tunnel/hosting) | ✔ | Tell us before changing Page admins or removing access |
| Watch health (silent channel, failed webhooks) | ✔ | |
| Config: hours, reply target, keywords, stages, alert recipients | ✔ (they request it) | Request changes |
| Weekly digest | ✔ sent automatically | Read it |
| Monthly review (30 min): leaks, trends, what to change | ✔ lead it | ✔ owner attends |
| Rule tuning (labels wrong, too many/few alerts) | ✔ | Flag wrong labels |
| Bug fixes | ✔ | Report with a screenshot |
| New features / new adapters | Quote separately | Request |
| Staff training | 30-min call + 1-page guide at start | New staff watch the guide |

## What we promise (our SLOs, draft numbers)

| Promise | Target | Measured by |
|---|---|---|
| Webhook intake up | 99% per month | uptime monitor on `/health` |
| Data freshness | new message visible within 5 min | "minutes since last webhook" vs Meta activity |
| Alert delivery | within 2 min of the threshold | alert `fired_at` vs threshold time |
| Silent-channel detection | we notice within 6 h of no webhooks during open hours | heartbeat alert to us |
| Support: urgent (data stopped, alerts not firing) | response in 4 business hours | support log |
| Support: normal (config change, question) | response in 1 business day, change in 2 | support log |
| Monthly review | held every month | calendar |

What we do **not** promise: their reply times (that's their target, we measure it), lead volume, or Meta platform outages.

## The client's targets (SLOs we measure for them)

Set at onboarding, shown in every report:
- First reply within N minutes during open hours (e.g. 15).
- No inquiry left unanswered past end of day.
- Hot leads answered within N minutes (e.g. 10).

## Change requests

| Type | Examples | Handling |
|---|---|---|
| Config (included) | hours, keywords, alert recipients, reply target | We do it within 2 business days |
| Small custom (included, capped) | a new label, a new digest line | Up to ~2 hours/month |
| New integration or feature | booking tool adapter, workflow agent, reactivation | Quote; Plus/Custom tier |

## Support channels

- One shared chat group per client (Viber/WhatsApp/Telegram, whatever they use).
- Tasks tracked in Notion or Linear (one board, a tag per client).
- Status page later (Uptime Kuma) once there are 3+ clients.

## Offboarding

Client removes our partner access; we export their data (CSV) on request and delete message bodies within 30 days, keeping only anonymous aggregates if the contract allows. Wording to confirm with a lawyer.
