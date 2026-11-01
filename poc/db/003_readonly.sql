-- Read-only login for dashboards (Grafana). Local-dev password; change it before any shared/hosted use.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'revobs_ro') THEN
    CREATE ROLE revobs_ro LOGIN PASSWORD 'revobs_ro';
  END IF;
END $$;
GRANT USAGE ON SCHEMA public TO revobs_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO revobs_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO revobs_ro;
