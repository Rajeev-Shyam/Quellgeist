"""SQLite connection + forward-only migrations (Wave 7, T7.1; DR-0023 decision 2).

Zero-infra persistence chosen for the RTX-5060 laptop constraint. **WAL mode** gives
concurrent readers alongside a single writer, which is exactly the service's shape: the
async ingress writes an incident while worker threads read/write runs. Every unit of
work opens its OWN short-lived connection (``sqlite3`` connections are single-thread by
default and the worker pool is multi-thread), so nothing is shared across threads;
``busy_timeout`` absorbs the brief writer contention WAL still serialises.

``init_db`` applies migrations once (at service startup / in test fixtures);
``connect`` just opens a configured connection. Migrations are forward-only ``.sql``
files under ``migrations/``, tracked in ``schema_migrations`` so re-running is a no-op.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a WAL-mode connection with foreign keys on and a row factory. The caller
    owns the connection (close it, or use it as a transaction context manager)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _applied_versions(conn: sqlite3.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_ts TEXT NOT NULL)"
    )
    return {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every ``migrations/NNN_*.sql`` not yet recorded, in numeric order, each in
    its own transaction. Returns the versions applied this call (empty on a no-op)."""
    from datetime import UTC, datetime

    done = _applied_versions(conn)
    applied: list[str] = []
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        version = sql_file.name.split("_", 1)[0]
        if version in done:
            continue
        with conn:  # transaction: all-or-nothing per migration
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_ts) VALUES (?, ?)",
                (version, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
        applied.append(version)
    return applied


def init_db(db_path: str | Path) -> None:
    """Open the DB and bring the schema up to date. Idempotent; call once at startup
    (and from test fixtures) before any DAO use."""
    conn = connect(db_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
