"""Data-access functions over a store connection (Wave 7, T7.1).

Thin, explicit SQL — no ORM. Every writer runs inside a ``with conn:`` transaction
(commit on success, rollback on error). Functions take an open connection so the caller
controls its lifetime and thread affinity (the worker opens its own connection in its
executor thread; the ingress opens one in the event-loop thread).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from quellgeist.store.models import Incident, RunRecord


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- incidents ------------------------------------------------------------------


def create_incident(conn: sqlite3.Connection, incident: Incident) -> None:
    with conn:
        conn.execute(
            "INSERT INTO incidents (id, source, received_ts, signals_ref, status, hint) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                incident.id,
                incident.source,
                incident.received_ts,
                incident.signals_ref,
                incident.status,
                incident.hint,
            ),
        )


def get_incident(conn: sqlite3.Connection, incident_id: str) -> Incident | None:
    row = conn.execute(
        "SELECT * FROM incidents WHERE id = ?", (incident_id,)
    ).fetchone()
    if row is None:
        return None
    return Incident(
        id=row["id"],
        source=row["source"],
        received_ts=row["received_ts"],
        signals_ref=row["signals_ref"],
        status=row["status"],
        hint=row["hint"],
    )


def set_incident_status(
    conn: sqlite3.Connection, incident_id: str, status: str
) -> None:
    with conn:
        conn.execute(
            "UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id)
        )


# --- runs -----------------------------------------------------------------------


def record_run(conn: sqlite3.Connection, run: RunRecord) -> None:
    with conn:
        conn.execute(
            "INSERT INTO runs (id, incident_id, model, started_ts, ended_ts, steps, "
            "outcome, abstained, fabricated, prompt_tokens, completion_tokens, "
            "latency_s, trace_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run.id,
                run.incident_id,
                run.model,
                run.started_ts,
                run.ended_ts,
                run.steps,
                run.outcome,
                int(run.abstained),
                run.fabricated,
                run.prompt_tokens,
                run.completion_tokens,
                run.latency_s,
                run.trace_json,
            ),
        )


def _run_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(
        id=row["id"],
        incident_id=row["incident_id"],
        model=row["model"],
        started_ts=row["started_ts"],
        ended_ts=row["ended_ts"],
        steps=row["steps"],
        outcome=row["outcome"],
        abstained=bool(row["abstained"]),
        fabricated=row["fabricated"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        latency_s=row["latency_s"],
        trace_json=row["trace_json"],
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> RunRecord | None:
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    return _run_from_row(row) if row else None


def list_runs(conn: sqlite3.Connection, incident_id: str) -> list[RunRecord]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE incident_id = ? ORDER BY started_ts", (incident_id,)
    ).fetchall()
    return [_run_from_row(r) for r in rows]


# --- diagnoses + evidence -------------------------------------------------------


def record_diagnosis(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    summary: str,
    diagnosis_json: str,
    verified_json: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO diagnoses (run_id, summary, diagnosis_json, verified_json) "
            "VALUES (?, ?, ?, ?)",
            (run_id, summary, diagnosis_json, verified_json),
        )


def record_evidence(
    conn: sqlite3.Connection,
    run_id: str,
    handles: list[tuple[int, str, str]],
) -> None:
    """Persist cited handles as ``(hyp_index, handle_type, handle_id)`` rows."""
    if not handles:
        return
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO evidence (run_id, hyp_index, handle_type, handle_id) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, hi, ht, str(hid)) for hi, ht, hid in handles],
        )


def set_review(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    decision: str,
    steer_text: str | None = None,
    reviewed_by: str | None = None,
) -> None:
    """Record an operator review decision (Wave 8 gate; schema-complete here)."""
    with conn:
        conn.execute(
            "UPDATE diagnoses SET review_decision = ?, steer_text = ?, reviewed_by = ? "
            "WHERE run_id = ?",
            (decision, steer_text, reviewed_by, run_id),
        )


# --- events (append-only audit log) ---------------------------------------------


def append_event(
    conn: sqlite3.Connection,
    incident_id: str,
    kind: str,
    *,
    detail_json: str | None = None,
    run_id: str | None = None,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO events (incident_id, run_id, ts, kind, detail_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (incident_id, run_id, _now(), kind, detail_json),
        )


def list_events(conn: sqlite3.Connection, incident_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM events WHERE incident_id = ? ORDER BY id", (incident_id,)
    ).fetchall()
    return [dict(r) for r in rows]
