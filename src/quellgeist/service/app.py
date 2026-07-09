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
import json
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from quellgeist import store
from quellgeist.clock import now_ts
from quellgeist.observability import configure_logging, get_logger
from quellgeist.service.config import ServiceConfig
from quellgeist.service.queue import WorkerPool
from quellgeist.service.security import verify_signature
from quellgeist.service.snapshots import snapshot_signals
from quellgeist.store import dao
from quellgeist.store.models import Incident

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
        except OSError as e:  # snapshot failed -> terminal, don't enqueue a doomed run
            dao.append_event(
                conn,
                incident_id,
                "failed",
                detail_json=json.dumps({"error": f"snapshot failed: {e}"}),
            )
            dao.set_incident_status(conn, incident_id, "failed")
            return 500, {"incident_id": incident_id, "status": "failed"}, False

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


def create_app(config: ServiceConfig) -> FastAPI:
    log = get_logger()
    pool = WorkerPool(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        store.init_db(config.db_path)
        await pool.start()
        log.info("service_started", workers=config.num_workers, db=config.db_path)
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
        body = await request.body()
        if (
            len(body) > config.max_body_bytes
        ):  # backstop if content-length was absent/lied
            raise HTTPException(status_code=413, detail="request body too large")
        if not verify_signature(
            config.webhook_secret, body, request.headers.get(_SIG_HEADER)
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

        status_code, out, should_enqueue = await asyncio.to_thread(
            _ingest_incident, config, incident_id, hint
        )
        if should_enqueue:
            await pool.enqueue(incident_id)
            log.info("incident_received", incident=incident_id)
        return JSONResponse(out, status_code=status_code)

    @app.get("/incidents/{incident_id}")
    def get_incident_ep(incident_id: str) -> dict:  # sync -> runs in a threadpool
        status = _incident_status(config, incident_id)
        if status is None:
            raise HTTPException(status_code=404, detail="unknown incident")
        return status

    return app
