"""FastAPI ingress + operator surface (Wave 7, T7.3; DR-0023 decision 1).

``POST /incidents`` is a signed webhook: cap+read the raw body, verify HMAC, validate the
payload, claim the incident id (idempotent INSERT), snapshot the operator's signals into a
per-incident dir, and enqueue. ``GET /healthz`` is the liveness probe; ``GET /incidents/{id}``
returns the incident + latest-run status as JSON (Wave 8 upgrades it to the HTML review
page). The worker pool (queue.py) runs the frozen loop off the event loop.

Hardening from the six-persona review:
- ``incident_id`` is allowlist-validated (``^[A-Za-z0-9_-]{1,128}$``) BEFORE it is used as a
  path segment or DB key — no path traversal via the webhook body.
- a non-object JSON body and a non-string ``hint`` return 400, not a 500.
- the request body is size-capped (413) before any work.
- the incident id is claimed (INSERT) **before** the snapshot is written, and the snapshot
  is atomic — no torn snapshot on a racing duplicate delivery.
- all blocking SQLite / file-copy work runs in a thread (``asyncio.to_thread`` / a sync
  ``def`` GET handler), so the event loop / ``/healthz`` never stall on WAL contention.

``create_app(config)`` is the injectable factory (tests pass a temp DB + scripted
provider); ``quellgeist.service:app`` builds the env instance lazily (see ``__init__``).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from quellgeist import store
from quellgeist.agent.schema import Diagnosis
from quellgeist.clock import now_ts
from quellgeist.notify import render_html
from quellgeist.observability import configure_logging, get_logger
from quellgeist.orchestrator.review import ReviewError, apply_review
from quellgeist.service.config import ServiceConfig
from quellgeist.service.queue import WorkerPool
from quellgeist.service.security import timestamp_within_skew, verify_signature
from quellgeist.service.snapshots import discard_snapshot, snapshot_signals
from quellgeist.store import dao
from quellgeist.store.models import Incident

_TS_HEADER = "x-quellgeist-timestamp"

_SIG_HEADER = "x-quellgeist-signature"
_INCIDENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _ingest_incident(
    config: ServiceConfig, incident_id: str, hint: str | None
) -> tuple[int, dict, bool]:
    """Blocking ingress work (runs in a thread): dedupe → claim id → atomic snapshot.
    Returns ``(status_code, response_payload, should_enqueue)``."""
    conn = store.connect(config.db_path)
    try:
        existing = dao.get_incident(conn, incident_id)
        if existing is not None:  # idempotent: duplicate delivery is a no-op
            return 200, {"incident_id": incident_id, "status": existing.status}, False

        snapshot_dir = Path(config.signals_dir) / incident_id
        try:  # claim the id FIRST so only the winner snapshots (no torn-snapshot race)
            dao.create_incident(
                conn,
                Incident(
                    id=incident_id,
                    source="webhook",
                    received_ts=now_ts(),
                    signals_ref=str(snapshot_dir),
                    status="queued",
                    hint=hint,
                ),
            )
        except sqlite3.IntegrityError:  # lost the race -> treat as duplicate
            got = dao.get_incident(conn, incident_id)
            return (
                200,
                {"incident_id": incident_id, "status": got.status if got else "queued"},
                False,
            )

        try:
            _, copied = snapshot_signals(
                snapshot_dir,
                log_path=config.log_path,
                deploy_path=config.deploy_path,
                metrics_path=config.metrics_path,
            )
        except OSError:  # snapshot failed -> treat as TRANSIENT and roll back the claim
            # so a retry can re-attempt, rather than permanently failing the incident
            # behind the idempotency short-circuit (a later duplicate delivery would
            # otherwise get 200 'failed' and never re-snapshot).
            dao.delete_incident(conn, incident_id)  # frees the id to re-claim
            return (
                503,
                {"incident_id": incident_id, "detail": "snapshot failed, retry later"},
                False,
            )

        dao.append_event(
            conn,
            incident_id,
            "received",
            detail_json=json.dumps({"snapshot_files": copied}),
        )
        return (
            202,
            {"incident_id": incident_id, "status": "queued", "snapshot_files": copied},
            True,
        )
    finally:
        conn.close()


def _incident_status(config: ServiceConfig, incident_id: str) -> dict | None:
    conn = store.connect(config.db_path)
    try:
        inc = dao.get_incident(conn, incident_id)
        if inc is None:
            return None
        runs = dao.list_runs(conn, incident_id)
        latest = runs[-1] if runs else None
        return {
            "incident_id": inc.id,
            "status": inc.status,
            "runs": len(runs),
            "latest_run": (
                {
                    "id": latest.id,
                    "outcome": latest.outcome,
                    "abstained": latest.abstained,
                    "fabricated": latest.fabricated,
                    "steps": latest.steps,
                    "prompt_tokens": latest.prompt_tokens,
                    "completion_tokens": latest.completion_tokens,
                    "latency_s": latest.latency_s,
                }
                if latest
                else None
            ),
        }
    finally:
        conn.close()


def _incident_page(config: ServiceConfig, incident_id: str) -> str | None:
    """Render the operator HTML page for an incident: the POST-VERIFIER diagnosis (or the
    raw one, clearly marked UNVERIFIED and not-postable), titled with the incident status.
    Returns None for an unknown incident (-> 404)."""
    conn = store.connect(config.db_path)
    try:
        inc = dao.get_incident(conn, incident_id)
        if inc is None:
            return None
        runs = dao.list_runs(conn, incident_id)
        latest = runs[-1] if runs else None
        diag_row = dao.get_diagnosis(conn, latest.id) if latest else None
    finally:
        conn.close()
    if diag_row and diag_row.get("verified_json"):
        diagnosis = Diagnosis.model_validate_json(diag_row["verified_json"])
        title = f"Incident {incident_id} — {inc.status} (verified)"
    elif diag_row and diag_row.get("diagnosis_json"):
        diagnosis = Diagnosis.model_validate_json(diag_row["diagnosis_json"])
        title = f"Incident {incident_id} — {inc.status} (UNVERIFIED — not postable)"
    else:
        diagnosis = Diagnosis(
            abstained=True, abstention_reason=f"no run yet (status: {inc.status})"
        )
        title = f"Incident {incident_id} — {inc.status}"
    return render_html(diagnosis, title=title)


async def _read_capped_body(request: Request, cap: int) -> bytes:
    """Read the request body, aborting with 413 as SOON as it exceeds ``cap``. Enforcing
    the bound while streaming (not via ``await request.body()`` + a post-hoc ``len``)
    bounds memory even when Content-Length is absent or lied about (chunked transfer),
    closing the unauthenticated-OOM hole — the cap is checked before any HMAC work."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > cap:
            raise HTTPException(status_code=413, detail="request body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _rollback_ingest(config: ServiceConfig, incident_id: str) -> None:
    """Undo a claimed-but-unqueued incident (queue-full load shed): free the id and drop
    its snapshot so a client retry can cleanly re-claim and re-enqueue."""
    conn = store.connect(config.db_path)
    try:
        dao.delete_incident(conn, incident_id)
    finally:
        conn.close()
    discard_snapshot(Path(config.signals_dir) / incident_id)


async def _recover_pending(config: ServiceConfig, pool: WorkerPool) -> int:
    """Re-enqueue incidents stranded by a restart/crash (status queued/running) — the
    in-memory queue does not survive a restart, but the persisted incident + its frozen
    snapshot do, and the run is re-derivable. Idempotent; returns the count re-enqueued.
    """

    def _fetch() -> list[str]:
        conn = store.connect(config.db_path)
        try:
            to_enqueue: list[str] = []
            for inc in dao.incidents_by_status(conn, ("queued", "running")):
                completed = any(
                    r.outcome in ("diagnosed", "abstained")
                    for r in dao.list_runs(conn, inc.id)
                )
                if completed:
                    # The run finished but the terminal 'pending_review' write was lost
                    # before the crash: reconcile the status, do NOT re-run (a re-run
                    # would persist a duplicate run for the same incident).
                    dao.set_incident_status(conn, inc.id, "pending_review")
                else:
                    to_enqueue.append(inc.id)
            return to_enqueue
        finally:
            conn.close()

    recovered = 0
    for incident_id in await asyncio.to_thread(_fetch):
        try:
            await pool.enqueue(incident_id)
            recovered += 1
        except asyncio.QueueFull:
            break  # queue saturated; the remainder recover on a later startup
    return recovered


def create_app(config: ServiceConfig) -> FastAPI:
    log = get_logger()
    pool = WorkerPool(config)

    # Per-incident-id serialization: a concurrent duplicate delivery must not observe a
    # transiently-claimed row that a rollback (queue-full / snapshot-fail) then deletes —
    # that would hand the duplicate a 200 'queued' for an incident which is then dropped.
    # Ref-counted so entries never leak (removed when the last holder releases).
    id_locks: dict[str, asyncio.Lock] = {}
    id_lock_refs: dict[str, int] = {}

    @asynccontextmanager
    async def _incident_lock(incident_id: str):
        lock = id_locks.get(incident_id)
        if lock is None:
            lock = id_locks[incident_id] = asyncio.Lock()
        id_lock_refs[incident_id] = id_lock_refs.get(incident_id, 0) + 1
        try:
            async with lock:
                yield
        finally:
            id_lock_refs[incident_id] -= 1
            if id_lock_refs[incident_id] == 0:
                id_locks.pop(incident_id, None)
                id_lock_refs.pop(incident_id, None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        store.init_db(config.db_path)
        await pool.start()
        recovered = await _recover_pending(config, pool)
        log.info(
            "service_started",
            workers=config.num_workers,
            db=config.db_path,
            recovered=recovered,
        )
        try:
            yield
        finally:
            await pool.stop()

    app = FastAPI(title="Quellgeist incident-response service", lifespan=lifespan)
    app.state.config = config
    app.state.pool = pool

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/incidents")
    async def create_incident_ep(request: Request) -> JSONResponse:
        cl = request.headers.get("content-length")
        if cl is not None and cl.isdigit() and int(cl) > config.max_body_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
        body = await _read_capped_body(request, config.max_body_bytes)
        # Replay window (opt-in): when enabled, require a fresh X-Quellgeist-Timestamp and
        # bind it into the signed material so a captured request can't be re-timestamped.
        ts = request.headers.get(_TS_HEADER)
        if config.webhook_max_skew_s > 0 and not timestamp_within_skew(
            ts, config.webhook_max_skew_s
        ):
            raise HTTPException(status_code=401, detail="stale or missing timestamp")
        signed_ts = ts if config.webhook_max_skew_s > 0 else None
        if not verify_signature(
            config.webhook_secret, body, request.headers.get(_SIG_HEADER), signed_ts
        ):
            raise HTTPException(status_code=401, detail="invalid or missing signature")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail="invalid JSON body") from e
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        incident_id = payload.get("id")
        if not isinstance(incident_id, str) or not _INCIDENT_ID_RE.match(incident_id):
            raise HTTPException(
                status_code=400,
                detail="id must be a string matching ^[A-Za-z0-9_-]{1,128}$",
            )
        hint = payload.get("hint")
        if hint is not None and not isinstance(hint, str):
            raise HTTPException(status_code=400, detail="hint must be a string")

        # Hold the per-id lock across claim -> enqueue/rollback so a concurrent duplicate
        # cannot see a row that is about to be rolled back.
        async with _incident_lock(incident_id):
            status_code, out, should_enqueue = await asyncio.to_thread(
                _ingest_incident, config, incident_id, hint
            )
            if should_enqueue:
                try:
                    await pool.enqueue(incident_id)
                except asyncio.QueueFull:
                    # Shed load cleanly: roll back the claim so a retry can re-enqueue,
                    # and tell the client to retry — never leave an incident orphaned.
                    await asyncio.to_thread(_rollback_ingest, config, incident_id)
                    log.warning("incident_shed_queue_full", incident=incident_id)
                    raise HTTPException(
                        status_code=503, detail="server busy, retry later"
                    ) from None
                log.info("incident_received", incident=incident_id)
        return JSONResponse(out, status_code=status_code)

    def _require_operator(request: Request) -> None:
        """Fail-closed bearer auth for the operator surface. An unset QG_OPERATOR_TOKEN
        rejects everything — this surface exposes run metadata AND the post action, so it
        must never be open by default (public repo)."""
        token = config.operator_token
        if not token:
            raise HTTPException(
                status_code=503, detail="operator surface not configured"
            )
        header = request.headers.get("authorization", "")
        prefix = "Bearer "
        presented = header[len(prefix) :] if header.startswith(prefix) else ""
        if not presented or not hmac.compare_digest(presented, token):
            raise HTTPException(
                status_code=401, detail="invalid or missing operator token"
            )

    @app.get("/incidents/{incident_id}", response_class=HTMLResponse)
    async def get_incident_page(incident_id: str, request: Request) -> HTMLResponse:
        _require_operator(request)
        page = await asyncio.to_thread(_incident_page, config, incident_id)
        if page is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        return HTMLResponse(page)

    @app.get("/incidents/{incident_id}/status")
    async def get_incident_status(incident_id: str, request: Request) -> dict:
        _require_operator(request)
        status = await asyncio.to_thread(_incident_status, config, incident_id)
        if status is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        return status

    @app.post("/incidents/{incident_id}/review")
    async def post_review(incident_id: str, request: Request) -> JSONResponse:
        _require_operator(request)
        try:
            payload = json.loads(
                await _read_capped_body(request, config.max_body_bytes)
            )
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail="invalid JSON body") from e
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="body must be a JSON object")
        steer_text, reviewed_by = payload.get("steer_text"), payload.get("reviewed_by")
        if steer_text is not None and not isinstance(steer_text, str):
            raise HTTPException(status_code=400, detail="steer_text must be a string")
        if reviewed_by is not None and not isinstance(reviewed_by, str):
            raise HTTPException(status_code=400, detail="reviewed_by must be a string")
        page_url = f"{str(request.base_url).rstrip('/')}/incidents/{incident_id}"
        try:
            # Serialize reviews per incident (same lock the ingress uses) so two concurrent
            # approves can't both pass the pending_review guard and double-post to Slack.
            async with _incident_lock(incident_id):
                out = await asyncio.to_thread(
                    apply_review,
                    incident_id,
                    decision=payload.get("decision"),
                    config=config,
                    steer_text=steer_text,
                    reviewed_by=reviewed_by,
                    page_url=page_url,
                )
        except ReviewError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e
        log.info(
            "incident_reviewed", incident=incident_id, decision=payload.get("decision")
        )
        return JSONResponse(out)

    return app
