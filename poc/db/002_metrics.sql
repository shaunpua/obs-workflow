-- Metrics layer: SQL views that turn raw messages/events into KPIs.
-- Dashboards (Metabase, Grafana, or the custom page) read only from these views.

-- Minutes between two timestamps that fall inside the client's business hours.
-- A 21:00 message answered at 09:10 next day = 10 business minutes, ~730 raw minutes.
CREATE OR REPLACE FUNCTION business_minutes(p_client TEXT, p_start TIMESTAMPTZ, p_end TIMESTAMPTZ)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE
  c clients%ROWTYPE;
  d DATE;
  win_start TIMESTAMPTZ;
  win_end TIMESTAMPTZ;
  total NUMERIC := 0;
BEGIN
  IF p_end IS NULL OR p_end <= p_start THEN RETURN 0; END IF;
  SELECT * INTO c FROM clients WHERE client_id = p_client;
  d := (p_start AT TIME ZONE c.timezone)::date;
  WHILE d <= (p_end AT TIME ZONE c.timezone)::date LOOP
    IF EXTRACT(ISODOW FROM d)::int = ANY (c.open_days) THEN
      win_start := (d + c.open_time) AT TIME ZONE c.timezone;
      win_end   := (d + c.close_time) AT TIME ZONE c.timezone;
      total := total + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(win_end, p_end) - GREATEST(win_start, p_start))) / 60);
    END IF;
    d := d + 1;
  END LOOP;
  RETURN round(total, 1);
END $$;

-- Was this moment inside business hours?
CREATE OR REPLACE FUNCTION in_business_hours(p_client TEXT, p_ts TIMESTAMPTZ)
RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
  SELECT EXTRACT(ISODOW FROM (p_ts AT TIME ZONE c.timezone))::int = ANY (c.open_days)
     AND (p_ts AT TIME ZONE c.timezone)::time >= c.open_time
     AND (p_ts AT TIME ZONE c.timezone)::time <  c.close_time
  FROM clients c WHERE c.client_id = p_client
$$;

-- Response-time pairs.
-- Rule: the clock starts at the FIRST customer message after the business last spoke,
-- and stops at the business's next message. Three customer messages in a row = one wait.
CREATE OR REPLACE VIEW v_reply_pairs AS
WITH m AS (
  SELECT *,
         COALESCE(SUM(CASE WHEN direction = 'out' THEN 1 ELSE 0 END) OVER (
           PARTITION BY lead_id ORDER BY sent_at, message_id
           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS outs_before
  FROM messages
),
waits AS (            -- one row per block of unanswered customer messages
  SELECT client_id, lead_id, outs_before AS block, MIN(sent_at) AS asked_at, COUNT(*) AS msgs_in_block
  FROM m WHERE direction = 'in'
  GROUP BY client_id, lead_id, outs_before
),
replies AS (          -- the business message that closes each block
  SELECT DISTINCT ON (lead_id, outs_before)
         lead_id, outs_before AS block, sent_at AS replied_at, actor AS replied_by
  FROM m WHERE direction = 'out'
  ORDER BY lead_id, outs_before, sent_at
)
SELECT w.client_id, w.lead_id, w.block,
       (w.block = 0)                                   AS is_first_response,
       w.asked_at, r.replied_at, r.replied_by, w.msgs_in_block,
       in_business_hours(w.client_id, w.asked_at)      AS asked_in_hours,
       ROUND(EXTRACT(EPOCH FROM (r.replied_at - w.asked_at)) / 60, 1) AS raw_minutes,
       business_minutes(w.client_id, w.asked_at, r.replied_at)        AS business_minutes
FROM waits w
LEFT JOIN replies r ON r.lead_id = w.lead_id AND r.block = w.block;

-- When each lead first reached each event type (span starts).
CREATE OR REPLACE VIEW v_lead_milestones AS
SELECT client_id, lead_id, event_type, MIN(occurred_at) AS reached_at, SUM(value) AS value
FROM events GROUP BY client_id, lead_id, event_type;

-- Daily KPI rollup per client.
CREATE OR REPLACE VIEW v_daily_kpis AS
SELECT p.client_id,
       (p.asked_at AT TIME ZONE c.timezone)::date                                       AS day,
       COUNT(*)                                                                         AS new_conversations,
       COUNT(*) FILTER (WHERE p.replied_at IS NULL)                                     AS never_answered,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.raw_minutes)                       AS frt_p50_min,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY p.raw_minutes)                       AS frt_p90_min,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY p.business_minutes)                  AS frt_p50_business_min,
       COUNT(*) FILTER (WHERE p.replied_by = 'ai')                                      AS answered_by_ai,
       COUNT(*) FILTER (WHERE NOT p.asked_in_hours)                                     AS after_hours
FROM v_reply_pairs p JOIN clients c USING (client_id)
WHERE p.is_first_response
GROUP BY 1, 2;
