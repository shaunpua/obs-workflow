# Connect your own Facebook Page (milestone 1)

> **Start with [`LOCAL_SETUP.md`](LOCAL_SETUP.md)** for the laptop and VS Code setup (install, `.env`, database, run buttons). This page covers the Meta dashboard side in more detail.

Goal: message your Page, reply from the inbox, and see both messages and the reply time in your database.
No Meta app review is needed for your own Page while the app is in **Development mode**.

> Meta's dashboard labels change often. If a menu is named differently, look for the Messenger product and its **Webhooks** and **Page token** settings. Official guides: [Messenger quick start](https://developers.facebook.com/documentation/business-messaging/messenger-platform/getting-started/quick-start) and [webhooks](https://developers.facebook.com/documentation/business-messaging/messenger-platform/webhooks).

## What you need before starting

| Thing | Where to get it |
|---|---|
| A Facebook developer account | developers.facebook.com → Get started (free) |
| Admin access to the Page | You already have this |
| **Page ID** | Page → About → Page transparency → Page ID, or the number in the Business Suite URL |
| A **second Facebook account** to send test messages | Any friend/alt account. Add it to the app as a Tester (step 3) |
| Docker (for Postgres) and Python 3.11+ | On your laptop |
| `cloudflared` (free tunnel) | `brew install cloudflared` or https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ |

Meta has to reach your laptop from the internet, so the app runs on **your machine** with a tunnel. It cannot run in the Claude cloud session.

Keep secrets (app secret, page token) on your machine only. Don't paste them into chats or commit them.

## 1. Start the app locally

See `LOCAL_SETUP.md` steps 1–5. In short: create `poc/.env` from `.env.example`, start the database with `docker compose up -d db`, then run `uvicorn app.main:app --port 8000` from `poc/`. The app loads `.env` itself.

Set now: `META_VERIFY_TOKEN` (any string) and `META_PAGE_ID`. The rest comes in the next steps (restart uvicorn after each change to `.env`).

## 2. Expose it with a tunnel

```bash
cloudflared tunnel --url http://localhost:8000
```

Copy the `https://….trycloudflare.com` address. It changes every time you restart the tunnel, so update Meta's webhook URL when it does.

## 3. Create the Meta app

1. developers.facebook.com → **My Apps → Create App**. Choose the option for a **Business** app / messaging with Messenger. Give it a name.
2. **Settings → Basic**: copy **App ID** → `META_APP_ID`, **App Secret** → `META_APP_SECRET`.
3. **App roles → Roles**: add your second account as **Tester** (they accept the invite at developers.facebook.com or in Notifications).
4. Leave the app in **Development** mode.

## 4. Add Messenger and the webhook

1. Add the **Messenger** product to the app → **Messenger API settings**.
2. **Webhooks → Configure**: Callback URL `https://<your-tunnel>/webhooks/meta`, Verify token = your `META_VERIFY_TOKEN`. Click **Verify and save**. (Meta calls your app; uvicorn's log shows the request.)
3. **Add or remove Pages** → add your Page. Then **Generate token** for it → copy to `META_PAGE_TOKEN`.
4. Under the Page's webhook subscriptions, tick: `messages`, `message_echoes`, `messaging_postbacks`, `messaging_referrals`, `message_reads`. If the dashboard doesn't let you pick fields, run the helper in step 5.

## 5. Subscribe the Page (and check it)

```bash
python -m scripts.subscribe_page          # subscribes the Page to the fields above
python -m scripts.subscribe_page --check  # shows what is subscribed
```

## 6. Test

1. From your **second account**, open your Page and send a message, e.g. `Hi! Available po ba sa Oct 18-19? 4 pax kami, magkano po?`
2. In **Meta Business Suite → Inbox**, reply by hand a minute later.
3. Look at what arrived:

```bash
python -m scripts.show_recent --client my-airbnb --raw
```

You should see one `← customer` message, one `→ customer … staff` message, the reply time in minutes, the lead labelled (probably **hot**), and two raw webhooks marked `processed=True`.

## If something doesn't show up

| Symptom | Likely cause |
|---|---|
| Verify and save fails | Tunnel not running, wrong URL (needs `/webhooks/meta`), or the verify token doesn't match |
| Your message never arrives | Page not subscribed (run `--check`), or the sender has no role on the app (Development mode only delivers for admins, developers and testers) |
| The message arrives but "unknown channel" is logged | `META_PAGE_ID` is wrong or missing. Restart uvicorn after changing it |
| 403 "bad signature" in the log | `META_APP_SECRET` is wrong |
| Customer message works, your inbox reply doesn't | `message_echoes` isn't subscribed |
| Names show as long numbers | `META_PAGE_TOKEN` missing or expired (names are fetched with it) |

## What is not covered yet

- Instagram DMs (add the IG account id once your IG is linked to the Page).
- Anyone without a role on the app. That needs Meta app review and business verification (start this early; it takes weeks).
- Old conversations (backfill comes in milestone 6).
