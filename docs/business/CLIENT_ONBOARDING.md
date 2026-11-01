# Client onboarding: what we need from them (DRAFT)

Status: draft. Edit freely as we learn what clients can and can't give us. Based on the POC (milestone 1) and `../POC_PLAN.md` section 11.

Two lists below: what the **client gives us**, and what **we do** with it. Keep the client list short; every extra ask slows go-live.

## Meta structure (how the pieces connect)

```
Our Meta app (Business type)
  └─ linked to a Business portfolio   ← ours for the POC; for a client, THEIR portfolio shares assets with ours
       ├─ Pages            (Facebook)
       ├─ Instagram accounts (professional, linked to the Page)
       └─ WhatsApp accounts (own number + own setup)
  └─ Use cases added to the app: Messenger (now), Instagram, WhatsApp (later)
```

Order for each client:
1. Their **Business portfolio** exists and owns the Page (and Instagram/WhatsApp).
2. They share those assets with us (partner or admin), so our app can see the Page.
3. App → **Business settings → Accounts → Apps**: our app is linked to the portfolio.
4. App → **Messenger use case → API settings**: Add Page → Generate token → subscribe fields → webhook URL.

POC today: app `Business` type, portfolio BackhomeBGC, Page BackHome Short Term Rentals, Instagram @backhomebgc (not wired), no WhatsApp.

## A. What we need from the client

### 1. Access (the part that takes the longest)

| Need | Why | How they do it | Notes |
|---|---|---|---|
| Facebook Page access for us | We read messages and reply times; we generate a Page token | Add us as **partner** on their Business portfolio (Business settings → Users → Partners), or add our person as **Page admin** | Partner is cleaner: they can remove us any time. Admin is simpler for small clients |
| **Page ID** | Routes webhooks to the right client | Business settings → Accounts → Pages (the ID under the Page name) | The long number, not the `profile.php?id=` one. Confirm with our `check_env` |
| Instagram account linked to the Page (optional) | Instagram DMs | Must be a professional account, linked in Business settings → Instagram accounts | Not built/tested yet in the POC |
| WhatsApp Business number (optional) | WhatsApp chats | Needs its own setup; the phone app can stay in use only with "Coexistence" | Not built/tested yet. Slowest channel; ask early |
| Consent to process their customers' messages | Legal | Signed agreement + data processing terms; privacy notice wording for their customers | Template still to write |

### 2. Business facts (one 15-minute call or a form)

| Need | Used for | Example |
|---|---|---|
| Business name, niche | Picks the config pack | "Glow Aesthetics", clinic |
| Opening hours and days, timezone | Fair reply-time measurement (after-hours messages aren't counted against them) | 09:00-20:00, Mon-Sat, Asia/Manila |
| Reply target | Alerts and reports | 15 minutes during hours |
| Who answers messages today | Who gets alerts; who is "staff" | Front desk (2 people), manager |
| Where alerts should go | Notifications | Telegram group (we create it; they add their staff) |
| Average value of a booking/sale | Pesos-at-risk figures | PHP 7,000 per stay |
| Their services/products and the words customers use | Lead interest tagging | Botox, laser, "pekas"; "staycation", "gabi" |
| How they sell: stages from inquiry to paid | Pipeline | Inquiry → dates shared → booked → checked in |
| Where bookings and payments are recorded | Later: tying messages to revenue | Cal.com, Google Sheet, PayMongo, or "in my head" |

### 3. Ground rules to agree up front
- Staff must reply **from the Page inbox (Meta Business Suite or Messenger app)**, not from personal accounts, or we can't see replies.
- We measure for 1-2 weeks **before changing anything** (the baseline), so the before/after numbers are honest.
- We only read messages; nothing is sent to their customers unless we agree a feature that does.
- They tell us before changing Page admins, or removing our access.

## B. What we do after they give us access

1. Add their Page to our Meta app (while the app is in Development mode, only people with a role on the app can message it; real customer traffic needs Meta app review and business verification, so start that process early).
2. Generate a Page token and subscribe the Page to `messages`, `message_echoes`, `messaging_postbacks`, `messaging_referrals`, `message_reads`.
3. Create `poc/config/clients/<client>.yaml` from the niche template: Page ID, hours, timezone, SLAs, alerts.
4. Send a test message from a tester account and reply from the inbox; confirm it appears on `/admin` with a reply time.
5. Optional one-time backfill of recent chats (marked `source=backfill`, never mixed into baseline numbers).
6. Start the baseline clock and record the date.
7. After 1-2 weeks: leak report, agreed targets, turn on alerts.

## C. Open questions (fill in as we learn)

- How do we hold multiple clients' Page tokens safely? (POC reads `META_PAGE_TOKENS` as a JSON map in `.env`; production needs a secrets store.)
- Self-serve "Connect your Page" button vs us doing it manually: when does it pay for itself? (Needs app review.)
- Which of Instagram/WhatsApp does the first paying client actually need?
- Data retention and deletion promise for customer messages.
- What do we do when a client's staff replies from a phone/personal account we can't see?

## D. Checklist to copy per client

- [ ] Agreement + data processing terms signed
- [ ] Partner/admin access to Page granted; Page ID confirmed
- [ ] Hours, timezone, reply target recorded
- [ ] Alert group created, staff added
- [ ] Client file created and loaded
- [ ] Webhook subscribed; test message and reply seen on `/admin`
- [ ] Staff briefed: reply from the Page inbox only
- [ ] Baseline start date recorded
- [ ] Baseline review booked (+2 weeks)
