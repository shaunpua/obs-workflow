-- Revenue Observability POC: core schema
-- Niche-agnostic. Everything niche-specific (stages, keywords, thresholds)
-- lives in YAML config, not in tables. Every table carries client_id.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- One row per business you serve (tenant).
CREATE TABLE IF NOT EXISTS clients (
  client_id   TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  niche       TEXT NOT NULL,                 -- clinic | solar | realestate | ...
  timezone    TEXT NOT NULL DEFAULT 'Asia/Manila',
  open_time   TIME NOT NULL DEFAULT '09:00', -- business hours, used for fair latency
  close_time  TIME NOT NULL DEFAULT '20:00',
  open_days   INT[] NOT NULL DEFAULT '{1,2,3,4,5,6}', -- ISO dow: 1=Mon .. 7=Sun
  config      JSONB NOT NULL DEFAULT '{}',   -- merged niche + client YAML
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Maps an incoming webhook (page id, IG id, WhatsApp phone_number_id) to a client.
CREATE TABLE IF NOT EXISTS channels (
  channel      TEXT NOT NULL,                -- messenger | instagram | whatsapp | chatwoot
  external_id  TEXT NOT NULL,                -- page_id / ig account id / phone_number_id
  client_id    TEXT NOT NULL REFERENCES clients(client_id),
  PRIMARY KEY (channel, external_id)
);

-- Every webhook body exactly as received. Lets you re-process when parsing changes.
CREATE TABLE IF NOT EXISTS raw_webhooks (
  id           BIGSERIAL PRIMARY KEY,
  source       TEXT NOT NULL,                -- meta | whatsapp | chatwoot | api
  received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  signature_ok BOOLEAN,
  payload      JSONB NOT NULL,
  processed_at TIMESTAMPTZ,
  error        TEXT
);

-- The lead database. One row per person per client (per channel for the POC;
-- cross-channel identity stitching comes later).
CREATE TABLE IF NOT EXISTS leads (
  lead_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id         TEXT NOT NULL REFERENCES clients(client_id),
  channel           TEXT NOT NULL,
  external_user_id  TEXT NOT NULL,           -- PSID / IGSID / wa_id
  display_name      TEXT,
  created_at        TIMESTAMPTZ NOT NULL,
  first_source      TEXT,                    -- ad | organic | referral ...
  first_ad_id       TEXT,
  stage             TEXT NOT NULL DEFAULT 'inquiry',
  temperature       TEXT,                    -- hot | warm | cold
  score             INT,
  intent            TEXT,
  interest          TEXT,
  est_value         NUMERIC,
  next_action       TEXT,
  next_action_priority INT,                  -- 1 = do now
  awaiting_reply    BOOLEAN NOT NULL DEFAULT false,
  waiting_since     TIMESTAMPTZ,             -- first unanswered inbound
  last_inbound_at   TIMESTAMPTZ,
  last_outbound_at  TIMESTAMPTZ,
  lost_reason       TEXT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, channel, external_user_id)
);

-- Logs: every message, both directions.
CREATE TABLE IF NOT EXISTS messages (
  message_id   TEXT PRIMARY KEY,             -- platform id (mid / wamid): dedupe key
  client_id    TEXT NOT NULL,
  lead_id      UUID NOT NULL REFERENCES leads(lead_id),
  channel      TEXT NOT NULL,
  direction    TEXT NOT NULL CHECK (direction IN ('in','out')),
  actor        TEXT NOT NULL,                -- customer | staff | ai
  sent_at      TIMESTAMPTZ NOT NULL,
  body         TEXT,
  app_id       TEXT,                         -- which app sent an echo (AI vs inbox)
  raw_id       BIGINT REFERENCES raw_webhooks(id)
);
CREATE INDEX IF NOT EXISTS messages_lead_time ON messages (lead_id, sent_at);

-- Traces: append-only business events. A lead's events in time order = its trace.
CREATE TABLE IF NOT EXISTS events (
  event_id     BIGSERIAL PRIMARY KEY,
  client_id    TEXT NOT NULL,
  lead_id      UUID NOT NULL REFERENCES leads(lead_id),
  event_type   TEXT NOT NULL,                -- lead_created, first_reply, consult_booked ...
  occurred_at  TIMESTAMPTZ NOT NULL,         -- real-world time
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor        TEXT,                         -- customer | staff | ai | system
  value        NUMERIC,
  props        JSONB NOT NULL DEFAULT '{}',
  dedupe_key   TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS events_lead_time ON events (lead_id, occurred_at);
CREATE INDEX IF NOT EXISTS events_client_type ON events (client_id, event_type, occurred_at);

-- History of every classification, so you can audit and measure accuracy.
CREATE TABLE IF NOT EXISTS lead_labels (
  id           BIGSERIAL PRIMARY KEY,
  lead_id      UUID NOT NULL REFERENCES leads(lead_id),
  labeled_at   TIMESTAMPTZ NOT NULL,
  method       TEXT NOT NULL,                -- rules | llm
  temperature  TEXT NOT NULL,
  score        INT,
  payload      JSONB NOT NULL
);

-- Alerts that fired (and when they were resolved).
CREATE TABLE IF NOT EXISTS alerts (
  id           BIGSERIAL PRIMARY KEY,
  client_id    TEXT NOT NULL,
  lead_id      UUID REFERENCES leads(lead_id),
  alert_type   TEXT NOT NULL,                -- hot_unanswered | escalation | integration_silent
  fired_at     TIMESTAMPTZ NOT NULL,
  resolved_at  TIMESTAMPTZ,
  message      TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS alerts_one_open
  ON alerts (lead_id, alert_type) WHERE resolved_at IS NULL;
