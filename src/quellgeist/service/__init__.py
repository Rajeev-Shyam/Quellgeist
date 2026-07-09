"""quellgeist.service — async FastAPI ingress + operator surface. Wave 7 (T7.3).

Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 1. A **signed inbound
webhook** triggers an investigation; accepted incidents are snapshotted (per-incident
isolation) and enqueued to a worker pool that runs the **synchronous** ``run_loop`` in a
thread executor — async lives only here, never in the frozen loop. Secrets are env-only;
the service is **fail-closed** (an empty webhook secret rejects all requests).

``create_app(config)`` is the injectable factory; ``app`` is the env-built instance for
``uvicorn quellgeist.service:app``.
"""

from __future__ import annotations

from quellgeist.service.app import app, create_app
from quellgeist.service.config import ServiceConfig

__all__ = ["ServiceConfig", "app", "create_app"]
