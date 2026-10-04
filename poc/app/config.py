"""Config loading: niche pack + client overrides -> one merged dict per client.

This is the flexibility mechanism. The engine code never mentions "botox" or
"solar"; it only reads stages, signals, interests, SLAs and next-action rules
from the merged config.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_client(path: Path) -> dict:
    client = yaml.safe_load(path.read_text())
    niche = yaml.safe_load((CONFIG_DIR / "niches" / f"{client['niche']}.yaml").read_text())
    merged = deep_merge(niche, client.get("overrides", {}))
    for key in ("client_id", "name", "niche", "timezone", "business_hours", "channels", "ai_app_id", "alerts"):
        if key in client:
            merged[key] = client[key]
    return merged


def load_all_clients() -> dict[str, dict]:
    return {c["client_id"]: c for c in (load_client(p) for p in sorted((CONFIG_DIR / "clients").glob("*.yaml")))}


def sync_clients_to_db(conn, clients: dict[str, dict]) -> None:
    """Upsert clients and their channel ids so webhooks can be routed."""
    with conn.cursor() as cur:
        for cfg in clients.values():
            hours = cfg.get("business_hours", {})
            cur.execute(
                """INSERT INTO clients (client_id, name, niche, timezone, open_time, close_time, open_days, config)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (client_id) DO UPDATE SET name=EXCLUDED.name, niche=EXCLUDED.niche,
                     timezone=EXCLUDED.timezone, open_time=EXCLUDED.open_time, close_time=EXCLUDED.close_time,
                     open_days=EXCLUDED.open_days, config=EXCLUDED.config""",
                (cfg["client_id"], cfg["name"], cfg["niche"], cfg.get("timezone", "Asia/Manila"),
                 hours.get("open", "09:00"), hours.get("close", "20:00"), hours.get("days", [1, 2, 3, 4, 5, 6]),
                 json.dumps(cfg)),
            )
            for channel, ch in cfg.get("channels", {}).items():
                cur.execute(
                    """INSERT INTO channels (channel, external_id, client_id) VALUES (%s,%s,%s)
                       ON CONFLICT (channel, external_id) DO UPDATE SET client_id=EXCLUDED.client_id""",
                    (channel, ch["external_id"], cfg["client_id"]),
                )
    conn.commit()
