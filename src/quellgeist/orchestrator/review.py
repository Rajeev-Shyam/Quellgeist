"""Human-in-the-loop review gate (Wave 8, T8.2; DR-0023 HITL).

Drives ``pending_review → approved|steered|rejected → posted``, auditing every transition
in ``events``:

- **approve** — publish the post-verifier diagnosis (fail-closed: refuses a fabricated OR
  unverified run) and mark the incident ``posted``.
- **reject** — record the decision, post nothing, mark ``rejected``.
- **steer** — re-run ``investigate`` over the SAME snapshot with the operator's steer text
  as a hint (a fresh run), returning the incident to ``pending_review``.

Blocking (DB + publish/investigate); the endpoint calls it via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from quellgeist import notify
from quellgeist.agent.schema import Diagnosis
from quellgeist.orchestrator.investigate import investigate
from quellgeist.service.snapshots import discard_snapshot
from quellgeist.store import connect, dao

if TYPE_CHECKING:
    from quellgeist.service.config import ServiceConfig

_DECISIONS = ("approve", "reject", "steer")


class ReviewError(Exception):
    """A review that cannot be applied (wrong state / missing / fail-closed refusal). The
    ``status_code`` maps directly to the HTTP response."""

    def __init__(self, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


def apply_review(
    incident_id: str,
    *,
    decision: str,
    config: ServiceConfig,
    steer_text: str | None = None,
    reviewed_by: str | None = None,
    page_url: str | None = None,
) -> dict:
    if decision not in _DECISIONS:
        raise ReviewError(f"decision must be one of {_DECISIONS}", 400)
    if decision == "steer" and not steer_text:
        raise ReviewError("a steer decision requires steer_text", 400)

    conn = connect(config.db_path)
    try:
        incident = dao.get_incident(conn, incident_id)
        if incident is None:
            raise ReviewError("unknown incident", 404)
        if incident.status != "pending_review":
            raise ReviewError(
                f"incident is '{incident.status}', not pending_review", 409
            )
        runs = dao.list_runs(conn, incident_id)
        if not runs:
            raise ReviewError("no run to review", 409)
        latest = runs[-1]
        diag_row = dao.get_diagnosis(conn, latest.id)
        fabricated = bool(latest.fabricated)  # '' = clean; a JSON list is truthy
        verified_json = diag_row.get("verified_json") if diag_row else None

        # Record the decision only AFTER any guard that can refuse it, so a refused
        # approve never persists review_decision='approve' on the diagnosis row.
        if decision == "reject":
            dao.set_review(conn, latest.id, decision="reject", reviewed_by=reviewed_by)
            dao.append_event(
                conn,
                incident_id,
                "rejected",
                run_id=latest.id,
                detail_json=json.dumps({"reviewed_by": reviewed_by}),
            )
            dao.set_incident_status(conn, incident_id, "rejected")
            # Terminal: nothing more reads this snapshot (Wave 9 completes reaping —
            # resolution verification reads live signals, not the frozen snapshot).
            discard_snapshot(incident.signals_ref)
            return {
                "incident_id": incident_id,
                "status": "rejected",
                "run_id": latest.id,
            }

        if decision == "steer":
            dao.set_review(
                conn,
                latest.id,
                decision="steer",
                steer_text=steer_text,
                reviewed_by=reviewed_by,
            )
            dao.append_event(
                conn,
                incident_id,
                "steered",
                run_id=latest.id,
                detail_json=json.dumps(
                    {"reviewed_by": reviewed_by, "steer": steer_text}
                ),
            )
            signals_ref, received_ts = incident.signals_ref, incident.received_ts
        else:  # approve — enforce fail-closed BEFORE recording the decision or posting
            if fabricated:
                raise ReviewError(
                    "cannot post a fabricated diagnosis (fail-closed)", 409
                )
            if not verified_json:
                raise ReviewError(
                    "cannot post an unverified diagnosis (fail-closed)", 409
                )
            dao.set_review(conn, latest.id, decision="approve", reviewed_by=reviewed_by)
    finally:
        conn.close()

    if decision == "steer":
        # A fresh run over the same isolated snapshot, steered by the operator's hint.
        investigate(
            incident_id,
            signals_ref,
            provider=config.make_provider(),
            db_path=config.db_path,
            model=config.model,
            hint=steer_text,
            verifier_provider=config.make_verifier_provider(),
            now=received_ts,
        )
        # Report the ACTUAL resulting status: the re-run normally lands pending_review,
        # but its terminal guard may degrade to 'failed' — don't claim pending_review then.
        conn = connect(config.db_path)
        try:
            steered = dao.get_incident(conn, incident_id)
        finally:
            conn.close()
        # The steer re-run runs INLINE here, not via the worker pool, so the worker's
        # terminal-'failed' snapshot reap never fires for it. Reap here when the re-run
        # degraded to persisted 'failed' (gated on the PERSISTED status, mirroring the
        # worker) so a steer-then-fail doesn't orphan the snapshot — completing Wave 9's
        # reaping for every terminal path. A pending_review re-run KEEPS its snapshot.
        if steered and steered.status == "failed":
            discard_snapshot(steered.signals_ref)
        return {
            "incident_id": incident_id,
            "status": steered.status if steered else "pending_review",
            "steered": True,
        }

    # approve — publish the VERIFIED diagnosis, then mark posted (idempotent: a second
    # approve sees status 'posted' and 409s above).
    verified = Diagnosis.model_validate_json(verified_json)
    emitted = notify.publish(
        verified,
        incident_id=incident_id,
        fabricated=False,
        config=config,
        page_url=page_url,
    )
    conn = connect(config.db_path)
    try:
        dao.append_event(
            conn,
            incident_id,
            "posted",
            run_id=latest.id,
            detail_json=json.dumps({"reviewed_by": reviewed_by, **emitted}),
        )
        dao.set_incident_status(conn, incident_id, "posted")
    finally:
        conn.close()
    # Terminal: reap the snapshot now that the diagnosis is posted. Resolution
    # verification (Wave 9) re-reads the operator's LIVE signals, so it needs no snapshot.
    discard_snapshot(incident.signals_ref)
    return {
        "incident_id": incident_id,
        "status": "posted",
        "run_id": latest.id,
        **emitted,
    }
