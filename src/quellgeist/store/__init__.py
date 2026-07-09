"""quellgeist.store — durable run history (SQLite WAL). Wave 7 (T7.1); DR-0023 decision 2.

Zero-infra persistence sized for the demo/portfolio: WAL gives concurrent readers
alongside a single writer. ``init_db`` applies forward-only migrations once; ``connect``
opens a configured, single-thread connection per unit of work; ``dao`` is the thin SQL
layer over the five tables (``incidents``, ``runs``, ``diagnoses``, ``evidence``,
``events``). Reads/writes only its own SQLite file (``QG_DB_PATH``); touches nothing
frozen.
"""

from __future__ import annotations

from quellgeist.store import dao
from quellgeist.store.db import apply_migrations, connect, init_db
from quellgeist.store.models import Incident, RunRecord

__all__ = [
    "Incident",
    "RunRecord",
    "apply_migrations",
    "connect",
    "dao",
    "init_db",
]
