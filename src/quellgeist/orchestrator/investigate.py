"""The resumable investigation around the FROZEN loop (Wave 7, T7.4; DR-0023 dec. 5).

``investigate`` is the synchronous core the worker runs (in a thread executor). It calls
``run_loop`` **exactly as the CLI does** — the measured artifact is never edited — over
this incident's isolated snapshot, then runs the deterministic fabrication check and
persists the full run (trace + cost + cited handles), leaving the incident in
``pending_review`` for the Wave-8 gate.

**Terminal-state guarantee (review):** the ENTIRE body is guarded, not just ``run_loop``
— a provider failure OR a failure in the persistence chain both degrade to a persisted
``failed`` run and a ``failed`` incident status (never a worker crash, never an incident
stuck at ``running``), and the diagnosis, if one was produced, is preserved in the
``failed`` event's detail so it is not lost (spec §Error handling).

NOTE (DR-0023 / PM review): the base **verifier** (``agent.verifier.verify``) is NOT yet
wired here — the live path is *fabrication-checked only*. Wiring the verifier before any
diagnosis is auto-posted is a Wave-8 prerequisite (T8.0); until then the live reliability
is the model's *intrinsic* behaviour, not the verifier-backed system number. Wave 8 adds
the review gate + hint injection and Wave 9 adds ``verify_resolution``.
``pending_review`` for the Wave-8 gate. Provider failures degrade to a persisted
``failed`` run, never a crashed worker.

Wave 8 adds the review gate + hint injection and Wave 9 adds ``verify_resolution``; both
wrap this same call. ``hint`` is accepted and stored now, injected in Wave 8.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quellgeist.agent.citations import check_fabrication
from quellgeist.agent.loop import LoopResult, run_loop
from quellgeist.agent.providers import Provider
from quellgeist.agent.schema import Diagnosis
from quellgeist.clock import now_ts
from quellgeist.observability import (
    get_logger,
    new_run_id,
    run_context,
    summarize_usage,
)
from quellgeist.orchestrator.tools_factory import incident_tools, read_signals
from quellgeist.store import connect, dao
from quellgeist.store.models import RunRecord

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_log = get_logger()


@dataclass
class InvestigationResult:
    run: RunRecord
    diagnosis: Diagnosis
    fabricated: list[tuple[str, object]]  # empty = clean


def _now() -> str:
    return datetime.now(UTC).strftime(_TS_FMT)


def _trace_json(result: LoopResult) -> str:
    return json.dumps(
        {
            "steps": result.steps,
            "tool_calls": [[name, args] for name, args in result.tool_calls],
            "schema_violations": result.schema_violations,
            "seen_handles": [list(h) for h in sorted(result.seen_handles, key=repr)],
            "messages": result.messages,
        },
        default=str,
    )


def _persist_failed(
    conn,
    *,
    incident_id: str,
    run_id: str,
    model: str,
    started: str,
    provider: Provider,
    diagnosis: Diagnosis | None,
    error: str,
) -> RunRecord:
    """Best-effort terminal persistence. Each write is independently guarded so one
    failing (e.g. a duplicate run row from a partial success) still lets the others run
    — the incident MUST leave ``running`` and the diagnosis MUST reach the event log."""
    usage = summarize_usage(provider)
    detail: dict = {"error": error}
    if diagnosis is not None:
        detail["diagnosis"] = json.loads(diagnosis.model_dump_json())
    run = RunRecord(
        id=run_id,
        incident_id=incident_id,
        model=model,
        started_ts=started,
        ended_ts=now_ts(),
        outcome="failed",
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        latency_s=usage.latency_s,
        trace_json=json.dumps(detail, default=str),
    )
    for op in (
        lambda: dao.record_run(conn, run),
        lambda: dao.append_event(
            conn,
            incident_id,
            "failed",
            run_id=run_id,
            detail_json=json.dumps(detail, default=str),
        ),
        lambda: dao.set_incident_status(conn, incident_id, "failed"),
    ):
        try:
            op()
        except Exception as pe:  # noqa: BLE001 - best-effort; never re-raise
            _log.error(
                "investigation_persist_failed", incident=incident_id, error=str(pe)
            )
    return run


def investigate(
    incident_id: str,
    snapshot_dir: str | Path,
    *,
    provider: Provider,
    db_path: str | Path,
    model: str,
    hint: str | None = None,
    now: str | None = None,
    max_steps: int = 8,
) -> InvestigationResult:
    """Run one investigation over an isolated snapshot and persist it. Opens its own
    store connection in the calling (worker) thread."""
    run_id = new_run_id()
    started = now_ts()
    now = now or started
    conn = connect(db_path)
    diagnosis: Diagnosis | None = None
    started = _now()
    now = now or started
    conn = connect(db_path)
    try:
        with run_context(incident_id, run_id):
            _log.info(
                "investigation_started",
                incident=incident_id,
                snapshot=str(snapshot_dir),
            )
            dao.set_incident_status(conn, incident_id, "running")
            try:
                result = run_loop(
                    provider, incident_tools(snapshot_dir), now=now, max_steps=max_steps
                )
                diagnosis = result.diagnosis
                logs, commits, metrics = read_signals(snapshot_dir)
                fabricated = sorted(
                    check_fabrication(diagnosis, logs, commits, metrics).fabricated,
                    key=repr,
                )
                usage = summarize_usage(provider)
                outcome = "abstained" if diagnosis.abstained else "diagnosed"
            except (
                Exception
            ) as exc:  # provider down / unexpected -> failed, not a crash
                _log.warning(
                    "investigation_failed", incident=incident_id, error=str(exc)
                )
                run = RunRecord(
                    id=run_id,
                    incident_id=incident_id,
                    model=model,
                    started_ts=started,
                    ended_ts=now_ts(),
                    steps=result.steps,
                    outcome=outcome,
                    abstained=diagnosis.abstained,
                    fabricated=(
                        json.dumps([list(h) for h in fabricated]) if fabricated else ""
                    ),
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    latency_s=usage.latency_s,
                    trace_json=_trace_json(result),
                )
                dao.record_run(conn, run)
                dao.record_diagnosis(
                    conn,
                    run_id,
                    summary=diagnosis.summary,
                    diagnosis_json=diagnosis.model_dump_json(),
                )
                dao.record_evidence(
                    conn,
                    run_id,
                    [
                        (i, ref.type, ref.ref_id)
                        for i, h in enumerate(diagnosis.hypotheses)
                        for ref in h.evidence
                    ],
                )
                dao.append_event(
                    conn,
                    incident_id,
                    outcome,
                    run_id=run_id,
                    detail_json=json.dumps(
                        {"fabricated": [list(h) for h in fabricated]}
                    ),
                )
                dao.set_incident_status(conn, incident_id, "pending_review")
                _log.info(
                    "investigation_done",
                    incident=incident_id,
                    outcome=outcome,
                    steps=result.steps,
                    fabricated=len(fabricated),
                    prompt_tokens=usage.prompt_tokens,
                )
                return InvestigationResult(run, diagnosis, fabricated)
            except Exception as exc:  # noqa: BLE001 - degrade to a persisted failure
                _log.warning(
                    "investigation_failed", incident=incident_id, error=str(exc)
                )
                run = _persist_failed(
                    conn,
                    incident_id=incident_id,
                    run_id=run_id,
                    model=model,
                    started=started,
                    provider=provider,
                    diagnosis=diagnosis,
                    error=str(exc),
                )
                fallback = diagnosis or Diagnosis(
                    abstained=True, abstention_reason=f"investigation failed: {exc}"
                )
                return InvestigationResult(run, fallback, [])
                    ended_ts=_now(),
                    outcome="failed",
                    trace_json=json.dumps({"error": str(exc)}),
                )
                dao.record_run(conn, run)
                dao.append_event(
                    conn,
                    incident_id,
                    "failed",
                    run_id=run_id,
                    detail_json=json.dumps({"error": str(exc)}),
                )
                dao.set_incident_status(conn, incident_id, "failed")
                return InvestigationResult(
                    run, Diagnosis(abstained=True, abstention_reason=str(exc)), []
                )

            diagnosis = result.diagnosis
            logs, commits, metrics = read_signals(snapshot_dir)
            fabricated = sorted(
                check_fabrication(diagnosis, logs, commits, metrics).fabricated,
                key=repr,
            )
            usage = summarize_usage(provider)
            outcome = "abstained" if diagnosis.abstained else "diagnosed"

            run = RunRecord(
                id=run_id,
                incident_id=incident_id,
                model=model,
                started_ts=started,
                ended_ts=_now(),
                steps=result.steps,
                outcome=outcome,
                abstained=diagnosis.abstained,
                fabricated=(
                    json.dumps([list(h) for h in fabricated]) if fabricated else ""
                ),
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                latency_s=usage.latency_s,
                trace_json=_trace_json(result),
            )
            dao.record_run(conn, run)
            dao.record_diagnosis(
                conn,
                run_id,
                summary=diagnosis.summary,
                diagnosis_json=diagnosis.model_dump_json(),
            )
            dao.record_evidence(
                conn,
                run_id,
                [
                    (i, ref.type, ref.ref_id)
                    for i, h in enumerate(diagnosis.hypotheses)
                    for ref in h.evidence
                ],
            )
            dao.append_event(
                conn,
                incident_id,
                outcome,
                run_id=run_id,
                detail_json=json.dumps({"fabricated": [list(h) for h in fabricated]}),
            )
            dao.set_incident_status(conn, incident_id, "pending_review")
            _log.info(
                "investigation_done",
                incident=incident_id,
                outcome=outcome,
                steps=result.steps,
                fabricated=len(fabricated),
                prompt_tokens=usage.prompt_tokens,
            )
            return InvestigationResult(run, diagnosis, fabricated)
    finally:
        conn.close()
