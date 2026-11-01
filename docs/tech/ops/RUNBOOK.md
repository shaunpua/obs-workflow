# Runbook: start, stop, and what to do when something breaks

Setup from scratch: [`LOCAL_SETUP.md`](LOCAL_SETUP.md). Meta dashboard clicks: [`SETUP_META.md`](SETUP_META.md).

## Start everything (from `poc/`)

1. `docker compose up -d db grafana`
2. App: VS Code Run and Debug → "App: run the webhook server" (or `.venv/bin/uvicorn app.main:app --port 8765`)
3. Tunnel: `cloudflared tunnel --url http://localhost:8765` → copy the `https://….trycloudflare.com` address
4. `python -m scripts.check_env --url https://<tunnel>` → all ok
5. If the tunnel address changed: Meta app → Messenger API settings → 1. Configure webhooks → Callback URL `https://<tunnel>/webhooks/meta`, Verify token = `META_VERIFY_TOKEN` → Verify and save

Look at data: `http://localhost:8765/admin?key=<API_KEY>` or Grafana `http://localhost:3100`.

## Known problems (all hit during the M1 test)

| Symptom | Cause | Fix |
|---|---|---|
| Tunnel hangs, log shows `failed to dial … quic` / `:7844 i/o timeout` | VPN or network blocks Cloudflare's tunnel port | Turn off the VPN, or try `--protocol http2`, or another network |
| Old callback URL stopped working | Quick tunnel gets a new address every restart | Update the Callback URL in Meta (step 5). Long-term: fixed address (named tunnel / ngrok domain / hosting) |
| "The callback URL or verify token couldn't be validated" | Wrong value in the Verify token box (we once pasted `API_KEY`) | Use `META_VERIFY_TOKEN`; app log shows the token Meta sent |
| `check_env` said token needs `pages_read_engagement` | Old check read the Page name | Fixed: check now uses `debug_token` |
| Guest shows as a number | Profile API refused | Fixed: falls back to the conversations list; retries at most every 10 min |
| Messages from a Page admin never count as a guest | Admins act as the Page | Test with a Tester account that is not a Page admin |
| First reply time looks like 0.1 min | Meta's automatic away message counts as a staff reply | Open: needs an "ignore auto-replies" rule per client |

## Health checks

- `/health` answers → app up.
- Grafana "Minutes since last webhook" orange/red → no traffic or Meta stopped delivering (check tunnel, subscriptions, token).
- "Failed to process" or "Bad signatures" above 0 → read `/admin/logs`.
