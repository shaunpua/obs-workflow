# Local setup in VS Code (start here)

Everything runs on your laptop. Your credentials stay in one file, `poc/.env`, which Git ignores. The app reads that file by itself, so there is nothing to `export`.

Time: about 30–45 minutes the first time, most of it in Meta's dashboard.

## 0. What to install once

| Tool | Check it works | Get it |
|---|---|---|
| VS Code | | https://code.visualstudio.com |
| Python 3.11 or newer | `python3 --version` (Windows: `py --version`) | https://www.python.org/downloads/ |
| Docker Desktop (for the database) | `docker --version` | https://www.docker.com/products/docker-desktop/ |
| cloudflared (free tunnel) | `cloudflared --version` | macOS: `brew install cloudflared`. Windows: `winget install Cloudflare.cloudflared`. Others: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ |
| Git | `git --version` | https://git-scm.com |

## 1. Get the code and open it

```bash
git clone https://github.com/shaunpua/obs-workflow.git
cd obs-workflow
git checkout claude/modest-bell-s4qaoo     # the branch with the POC, until it is merged
code .
```

VS Code will offer to install the recommended extensions (Python, Pylance, Docker, YAML). Accept.

## 2. Python environment (in the VS Code terminal)

```bash
cd poc
python3 -m venv .venv                      # Windows: py -m venv .venv
source .venv/bin/activate                  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Then press `Cmd/Ctrl+Shift+P` → **Python: Select Interpreter** → pick the one inside `poc/.venv`.

## 3. Start the database

Run the task: `Cmd/Ctrl+Shift+P` → **Tasks: Run Task** → **1. Database: start (Docker)**.
(Or in the terminal: `docker compose up -d db`.) Docker Desktop must be open.

## 4. Create your `.env`

```bash
cp .env.example .env                       # Windows: copy .env.example .env
```

Open `poc/.env` in VS Code. Fill these in as you collect them:

| Variable | Value | Where it comes from |
|---|---|---|
| `DATABASE_URL` | leave as is | The Docker database from step 3 |
| `META_VERIFY_TOKEN` | any text you make up, e.g. `my-verify-2026` | You choose it. You'll type the same text into Meta |
| `API_KEY` | any text you make up | You choose it |
| `META_PAGE_ID` | your Page's numeric ID | Facebook Page → About → Page transparency → Page ID |
| `META_APP_ID` | number | Meta app → Settings → Basic |
| `META_APP_SECRET` | long hex string | Meta app → Settings → Basic → App secret → Show |
| `META_PAGE_TOKEN` | long string starting with `EAA…` | Meta app → Messenger → API settings → Generate token for your Page |

**Treat `META_APP_SECRET` and `META_PAGE_TOKEN` like passwords.** Never paste them into chat, a commit, a screenshot or an issue. If one leaks, regenerate it in Meta (about a minute). `.env` is already in `.gitignore`; check with `git status` that it never shows up.

## 5. Check the app works before touching Meta

1. Start the app: **Run and Debug** (left bar) → **App: run the webhook server** → ▶. (Or terminal: `uvicorn app.main:app --port 8000 --reload`.)
2. Run **Script: send a fake test message**. It sends a signed fake guest message and a staff reply to your own local app.
3. Run **Script: show what was received**. You should see the guest message, the staff reply, a reply time of about 3 minutes, and the lead labelled (probably hot).

If that works, the whole pipeline is fine and only the Meta connection is left. (Needs `META_APP_SECRET` and `META_PAGE_ID` set; use any placeholder values for a dry run.)

## 6. Connect Meta

Keep the app running. Open a second terminal and run the task **2. Tunnel: expose port 8000 (cloudflared)**. Copy the `https://….trycloudflare.com` address it prints.

Run **3. Check my setup** (or `python -m scripts.check_env --url https://<your-tunnel>`). It tells you exactly which variable is missing or wrong, whether your Page token works, and whether Meta's verification will pass.

Then follow `docs/SETUP_META.md` for the dashboard clicks: create the app, add Messenger, set the webhook URL to `https://<your-tunnel>/webhooks/meta` with your verify token, add your Page, tick the event fields, and run **4. Subscribe my Page to Meta events**.

## 7. Test with real messages

1. From your **second Facebook account** (added to the app as a Tester), send your Page a message.
2. Reply from **Meta Business Suite → Inbox**.
3. Run **5. Show what was received**.

Done when you see the guest's message, your reply as `staff`, and the reply time.

## Everyday commands

| Want to | Do |
|---|---|
| Start the app | Run and Debug → App: run the webhook server |
| Stop the app | Stop button, or `Ctrl+C` |
| See what arrived | Task 5, or `python -m scripts.show_recent --client my-airbnb --raw` |
| Look inside the database | `docker compose exec db psql -U revobs revobs` then e.g. `SELECT * FROM v_reply_pairs;` |
| Run the tests | Task **Run tests** (needs a `revobs_test` database; see `tests/conftest.py`) |
| Tunnel URL changed after a restart | Update the Callback URL in Meta → Webhooks (the quick tunnel gets a new address each run) |
| Edited `.env` | Restart the app |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `check_env` says Postgres can't connect | Docker Desktop isn't running, or task 1 wasn't run |
| "Verify and save" fails in Meta | Tunnel not running, URL missing `/webhooks/meta`, verify token differs from `.env`, or you didn't restart the app after editing `.env`. `check_env --url …` shows which |
| Message from your second account never arrives | Not added as Tester, the Page isn't subscribed (run task 4, then `python -m scripts.subscribe_page --check`), or the app isn't in Development mode with your Page added |
| Log says "webhook for unknown messenger id" | `META_PAGE_ID` in `.env` is wrong. Copy the id shown in that log line |
| 403 "bad signature" | `META_APP_SECRET` is wrong |
| Names show as long numbers | `META_PAGE_TOKEN` missing or expired |
| Windows: script won't activate the venv | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once in PowerShell |

## Later: moving off your laptop

When this works, the same settings go into a hosted server's environment variables (never into the code), and you update the Meta webhook URL once. See the hosting notes in `docs/POC_IMPLEMENTATION.md`.
