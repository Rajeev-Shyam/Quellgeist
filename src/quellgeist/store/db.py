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


def _statements(script: str) -> list[str]:
    """Split a migration ``.sql`` into individual statements. Line comments (``-- ...``)
    are stripped and the script is split on ``;``. Migrations must therefore be simple
    DDL/DML with no semicolons inside string literals or triggers — sufficient for this
    store's forward-only schema, and it lets us run each statement under our OWN explicit
    transaction (``executescript`` force-commits, which is exactly the atomicity hole).
    """
    no_comments = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Apply every ``migrations/NNN_*.sql`` not yet recorded, in numeric order.

    The whole check-then-apply runs inside a single ``BEGIN IMMEDIATE`` transaction, so:
    (1) it is **serialized** across processes — a second starter blocks on the write lock,
    then sees the versions already applied and no-ops (no "table already exists" crash);
    (2) each migration's DDL and its ``schema_migrations`` row commit **atomically** — a
    crash mid-apply rolls the whole thing back rather than leaving a partial, unrecorded
    schema that bricks the next startup. Returns the versions applied this call."""
    from datetime import UTC, datetime

    prev_isolation = conn.isolation_level
    conn.isolation_level = None  # take manual control of BEGIN/COMMIT/ROLLBACK
    try:
        conn.execute("BEGIN IMMEDIATE")  # acquire the write lock up front
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_ts TEXT NOT NULL)"
        )
        done = {
            r["version"] for r in conn.execute("SELECT version FROM schema_migrations")
        }
        applied: list[str] = []
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = sql_file.name.split("_", 1)[0]
            if version in done:
                continue
            for stmt in _statements(sql_file.read_text(encoding="utf-8")):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_ts) VALUES (?, ?)",
                (version, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")),
            )
            applied.append(version)
        conn.execute("COMMIT")
        return applied
    except BaseException:
        # Only roll back if a transaction is actually open. If BEGIN IMMEDIATE itself
        # failed (write-lock contention — the serialized-starter case), no transaction
        # exists and an unconditional ROLLBACK would raise, masking the real error.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = prev_isolation


def init_db(db_path: str | Path) -> None:
    """Open the DB and bring the schema up to date. Idempotent; call once at startup
    (and from test fixtures) before any DAO use."""
    conn = connect(db_path)
    try:
        apply_migrations(conn)
    finally:
        conn.close()
