"""FastAPI ingress + operator surface (Wave 7, T7.3; DR-0023 decision 1).

``POST /incidents`` is a signed webhook: verify HMAC over the raw body, dedupe on the
incident id (idempotent), snapshot the operator's signals into a per-incident dir, and
enqueue. ``GET /healthz`` is the liveness probe; ``GET /incidents/{id}`` returns the
incident + latest-run status as JSON (Wave 8 upgrades it to the HTML review page). The
worker pool (queue.py) runs the frozen loop off the event loop.

``create_app(config)`` is the injectable factory (tests pass a temp DB + scripted
provider); the module-level ``app`` is built from the environment for ``uvicorn
quellgeist.service:app``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from quellgeist import store
from quellgeist.observability import configure_logging, get_logger
from quellgeist.service.config import ServiceConfig
from quellgeist.service.queue import WorkerPool
from quellgeist.service.security import verify_signature
from quellgeist.service.snapshots import snapshot_signals
from quellgeist.store import dao
from quellgeist.store.models import Incident

_SIG_HEADER = "x-quellgeist-signature"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        body = await request.body()
        if not verify_signature(
            config.webhook_secret, body, request.headers.get(_SIG_HEADER)
        ):
            raise HTTPException(status_code=401, detail="invalid or missing signature")
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail="invalid JSON body") from e
        incident_id = payload.get("id")
        if not incident_id or not isinstance(incident_id, str):
            raise HTTPException(status_code=400, detail="missing string incident id")
        hint = payload.get("hint")

        conn = store.connect(config.db_path)
        try:
            existing = dao.get_incident(conn, incident_id)
            if existing is not None:  # idempotent: duplicate delivery is a no-op
                return JSONResponse(
                    {"incident_id": incident_id, "status": existing.status},
                    status_code=200,
                )
            snapshot_dir = Path(config.signals_dir) / incident_id
            snapshot_signals(
                snapshot_dir,
                log_path=config.log_path,
                deploy_path=config.deploy_path,
                metrics_path=config.metrics_path,
            )
            try:
                dao.create_incident(
                    conn,
                    Incident(
                        id=incident_id,
                        source="webhook",
                        received_ts=_now(),
                        signals_ref=str(snapshot_dir),
                        status="queued",
                        hint=hint,
                    ),
                )
            except sqlite3.IntegrityError:  # lost an idempotency race -> treat as dup
                got = dao.get_incident(conn, incident_id)
                return JSONResponse(
                    {
                        "incident_id": incident_id,
                        "status": got.status if got else "queued",
                    },
                    status_code=200,
                )
            dao.append_event(conn, incident_id, "received")
        finally:
            conn.close()

        await pool.enqueue(incident_id)
        log.info("incident_received", incident=incident_id)
        return JSONResponse(
            {"incident_id": incident_id, "status": "queued"}, status_code=202
        )

    @app.get("/incidents/{incident_id}")
    async def get_incident_ep(incident_id: str) -> dict:
        conn = store.connect(config.db_path)
        try:
            inc = dao.get_incident(conn, incident_id)
            if inc is None:
                raise HTTPException(status_code=404, detail="unknown incident")
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

    return app


# Built from the environment for `uvicorn quellgeist.service:app`. Constructing the app
# starts no workers (that happens in the lifespan), so import is side-effect-light.
app = create_app(ServiceConfig.from_env())
