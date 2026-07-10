"""quellgeist.service — async FastAPI ingress + operator surface. Wave 7 (T7.3).

Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 1. A **signed inbound
webhook** triggers an investigation; accepted incidents are snapshotted (per-incident
isolation) and enqueued to a worker pool that runs the **synchronous** ``run_loop`` in a
thread executor — async lives only here, never in the frozen loop. Secrets are env-only;
the service is **fail-closed** (an empty webhook secret rejects all requests).

``create_app(config)`` is the injectable factory. ``quellgeist.service:app`` resolves a
lazily-built env instance for ``uvicorn`` (built on first access, NOT at import — so
importing this package for ``ServiceConfig`` / ``create_app`` never parses the env or
constructs the app; review: import side-effects).
"""

from __future__ import annotations

from quellgeist.service.app import create_app
from quellgeist.service.config import ServiceConfig

__all__ = ["ServiceConfig", "app", "create_app"]

_app = None


def __getattr__(name: str):
    # PEP 562 module-level lazy attribute: build `app` from the environment only when
    # something (uvicorn) actually asks for `quellgeist.service:app`.
    if name == "app":
        global _app
        if _app is None:
            _app = create_app(ServiceConfig.from_env())
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
