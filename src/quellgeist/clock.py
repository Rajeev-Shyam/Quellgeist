"""Canonical UTC timestamp helper (shared).

One definition of "now" in the canonical zero-padded ``%Y-%m-%dT%H:%M:%SZ`` UTC form
the tools compare lexicographically (DR-0009), so the store, orchestrator, and service
don't each re-derive it (review: de-duplicated ``_now``).
"""

from __future__ import annotations

from datetime import UTC, datetime

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_ts() -> str:
    return datetime.now(UTC).strftime(_TS_FMT)
