import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://revobs:revobs@localhost:5432/revobs")
DB_DIR = Path(__file__).resolve().parent.parent / "db"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def migrate(conn: psycopg.Connection) -> None:
    for sql_file in sorted(DB_DIR.glob("*.sql")):
        conn.execute(sql_file.read_text())
    conn.commit()
