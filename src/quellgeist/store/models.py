"""Row dataclasses for the store (Wave 7, T7.1).

Lightweight, framework-free mirrors of the schema rows the DAO reads/writes. The
orchestrator builds a ``RunRecord`` and hands it to ``dao.record_run``; the service
builds an ``Incident``. Kept separate from the pydantic ``Diagnosis`` (that is the
frozen agent contract) — these are persistence rows, not the model's output schema.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Incident:
    id: str
    source: str  # 'webhook' | 'cli' | 'poll'
    received_ts: str  # canonical UTC
    signals_ref: str  # per-incident snapshot dir
    status: str  # queued|running|pending_review|posted|rejected|failed
    hint: str | None = None


@dataclass
class RunRecord:
    id: str
    incident_id: str
    model: str
    started_ts: str
    ended_ts: str | None = None
    steps: int | None = None
    outcome: str = "failed"  # diagnosed | abstained | failed
    abstained: bool = False
    # '' = checked-clean, JSON list = fabricated handles, None = unverified
    fabricated: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_s: float | None = None
    trace_json: str | None = None
