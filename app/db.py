"""SQLite persistence layer (stdlib sqlite3, WAL mode).

The DB is shared between the FastAPI container (read/write) and the Streamlit
container (read-only) via a named Docker volume mounted at /data. WAL mode lets
both processes touch the same file without blocking each other.
"""
import json
import os
import sqlite3
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS remediations (
  issue_number      INTEGER PRIMARY KEY,
  issue_title       TEXT,
  category          TEXT,
  state             TEXT,
  session_id        TEXT,
  session_url       TEXT,
  status            TEXT,
  status_detail     TEXT,
  pr_url            TEXT,
  pr_state          TEXT,
  structured_output TEXT,
  acus_consumed     REAL DEFAULT 0,
  created_at        TEXT,
  launched_at       TEXT,
  completed_at      TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def init_db() -> None:
    """Create the data dir + table if they don't exist yet."""
    os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)


def insert_remediation(row: dict[str, Any]) -> None:
    """Insert a new remediation row. Ignores if issue_number already present."""
    cols = (
        "issue_number", "issue_title", "category", "state",
        "created_at",
    )
    with _connect() as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO remediations ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)})",
            tuple(row.get(c) for c in cols),
        )


def update_remediation(issue_number: int, **fields: Any) -> None:
    """Patch arbitrary columns for a given issue. structured_output is JSON-encoded if dict/list."""
    if not fields:
        return
    if isinstance(fields.get("structured_output"), (dict, list)):
        fields["structured_output"] = json.dumps(fields["structured_output"])
    assignments = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [issue_number]
    with _connect() as conn:
        conn.execute(
            f"UPDATE remediations SET {assignments} WHERE issue_number = ?",
            values,
        )


def get_remediation(issue_number: int) -> Optional[dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT * FROM remediations WHERE issue_number = ?", (issue_number,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_all(order_by: str = "created_at DESC") -> list[dict[str, Any]]:
    with _connect() as conn:
        cur = conn.execute(f"SELECT * FROM remediations ORDER BY {order_by}")
        return [dict(r) for r in cur.fetchall()]


def get_by_state(*states: str) -> list[dict[str, Any]]:
    if not states:
        return []
    placeholders = ", ".join("?" for _ in states)
    with _connect() as conn:
        cur = conn.execute(
            f"SELECT * FROM remediations WHERE state IN ({placeholders})", states
        )
        return [dict(r) for r in cur.fetchall()]


def count_by_state(*states: str) -> int:
    if not states:
        return 0
    placeholders = ", ".join("?" for _ in states)
    with _connect() as conn:
        cur = conn.execute(
            f"SELECT COUNT(*) FROM remediations WHERE state IN ({placeholders})", states
        )
        return int(cur.fetchone()[0])


def exists(issue_number: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "SELECT 1 FROM remediations WHERE issue_number = ?", (issue_number,)
        )
        return cur.fetchone() is not None
