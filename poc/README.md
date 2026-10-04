# Revenue Observability POC

Status: first version, paused for plan review. Read [`../docs/POC_PLAN.md`](../docs/POC_PLAN.md) first.

## Run on simulated data

```bash
pip install -r requirements.txt
docker run -d --name revobs-db -e POSTGRES_USER=revobs -e POSTGRES_PASSWORD=revobs -e POSTGRES_DB=revobs -p 5432:5432 postgres:16
export DATABASE_URL=postgresql://revobs:revobs@localhost:5432/revobs

python -m scripts.simulate                          # 14 days of clinic chats, sent as signed Meta webhooks
python -m scripts.build_dashboard --standalone      # writes out/dashboard.html
```

## Run against your own Facebook Page

```bash
export META_APP_SECRET=...        # Meta app → Settings → Basic
export META_VERIFY_TOKEN=any-string-you-choose
uvicorn app.main:app --port 8000
cloudflared tunnel --url http://localhost:8000     # gives you a public https URL
```

Then follow section 10 of the plan: webhook URL `https://<tunnel>/webhooks/meta`,
subscribe your Page to `messages` and `message_echoes`, and put your Page id in a
file under `config/clients/`.

## Layout

| Path | What |
|---|---|
| `app/` | webhook receiver, adapters, pipeline, classifier, alerts |
| `db/` | schema + metric views |
| `config/niches/` | niche packs (clinic, solar) |
| `config/clients/` | per-client overrides |
| `scripts/` | simulator, dashboard builder |
| `dashboard/` | dashboard HTML template |
