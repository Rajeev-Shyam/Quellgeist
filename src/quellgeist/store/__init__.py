"""quellgeist.store — durable run history (SQLite WAL). SCAFFOLD (Wave 7, T7.1).

Not yet implemented. This package is the v2 persistence layer per
[DR-0023](../../../docs/quellgeist-adr-log.md) decision 2 and the
[v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. Wave 7 fills it in; the
plan opens with the writing-plans flow, so nothing here is built ahead of its wave.

Planned surface (see the spec for the DDL):
- ``connect() -> sqlite3.Connection`` — WAL-mode connection.
- DAO: ``create_incident``, ``record_run``, ``append_event``, ``set_review``,
  ``get_incident``, ``list_runs``.
- ``migrations/`` — forward-only schema (`incidents`, `runs`, `diagnoses`,
  `evidence`, `events`).

Reuses nothing frozen; reads/writes only its own SQLite file (``QG_DB_PATH``).
"""

from __future__ import annotations

__all__: list[str] = []
