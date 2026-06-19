"""Quellgeist toy demo service.

Emits one structured JSON log record per request to a JSONL file — the "real
signal" the agent later diagnoses. Each record carries a SOURCE-STABLE monotonic
`id` assigned at emit time (DR-0009): the id LogRef cites, in ingest order, never
the position within a filtered query. Record shape matches
evals/scenarios/fixtures/bad_deploy_0001.json exactly:
    {"id", "ts", "level", "route", "status", "msg"}
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from demo.app import auth

# --- structured-log sink ----------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
LOG_PATH = Path(os.getenv("QG_LOG_PATH", _REPO_ROOT / "demo" / "incident_logs.jsonl"))
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
LOG_PATH.write_text("")  # fresh log each app session
_log_file = LOG_PATH.open(
    "a", buffering=1
)  # append (O_APPEND): safe even if reset truncates mid-session

_id_lock = threading.Lock()
_next_id = 0


def _add_ingest_id(_logger, _method, event_dict):
    """Assign a source-stable monotonic id at emit time (DR-0009)."""
    global _next_id
    with _id_lock:
        event_dict["id"] = _next_id
        _next_id += 1
    return event_dict


def _uppercase_level(_logger, _method, event_dict):
    lvl = event_dict.get("level")
    if isinstance(lvl, str):
        event_dict["level"] = lvl.upper()  # INFO/ERROR, matching the fixture
    return event_dict


structlog.configure(
    processors=[
        _add_ingest_id,
        structlog.processors.add_log_level,
        _uppercase_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%SZ", utc=True, key="ts"),
        structlog.processors.EventRenamer("msg"),  # event -> msg
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.WriteLoggerFactory(file=_log_file),
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()

# --- metrics (stub now; used properly in Wave 3) ----------------------------

REQUESTS = Counter("qg_requests_total", "Total requests", ["route", "status"])
ERRORS = Counter("qg_errors_total", "Total 5xx responses", ["route"])
IN_FLIGHT = Gauge("qg_in_flight_requests", "In-flight requests")

# --- app --------------------------------------------------------------------

app = FastAPI(title="Quellgeist demo service")


@app.middleware("http")
async def observe(request: Request, call_next):
    route = request.url.path
    if route == "/metrics":  # don't log or count the scrape itself
        return await call_next(request)

    IN_FLIGHT.inc()
    try:
        response = await call_next(request)
    except Exception as exc:  # an endpoint raised (e.g. a Task 3 injected regression)
        REQUESTS.labels(route=route, status="500").inc()
        ERRORS.labels(route=route).inc()
        log.error(f"{type(exc).__name__}: {exc}", route=route, status=500)
        raise  # let Starlette turn it into a 500
    finally:
        IN_FLIGHT.dec()

    status = response.status_code
    REQUESTS.labels(route=route, status=str(status)).inc()
    if status >= 500:
        ERRORS.labels(route=route).inc()
        log.error("request failed", route=route, status=status)
    return response


@app.get("/health")
def health():
    log.info("health ok", route="/health", status=200)
    return {"status": "ok"}


@app.get("/login")  # GET for curl-ability; method is irrelevant to diagnosis
def login(request: Request):
    result = auth.verify_token(request.headers.get("authorization"))
    log.info("login ok", route="/login", status=200)
    return {"token": "demo-token", "user": result["user"]}


@app.get("/data")
def data():
    log.info("data served", route="/data", status=200)
    return {"data": [1, 2, 3]}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
