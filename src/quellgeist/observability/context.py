"""Correlation context: per-incident + per-run ids bound to structlog (Wave 7, T7.2).

`run_context` binds ``incident_id`` and ``run_id`` into structlog's ``contextvars``
store for the duration of a run, so every log line emitted anywhere in the loop /
orchestrator is correlation-tagged without threading the ids through call signatures.
``contextvars`` are the right primitive: the worker runs each investigation in its own
executor thread, and a `ContextVar` context is copied to that thread, so ids stay
isolated per run even under concurrency.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator

import structlog


def new_run_id() -> str:
    """A short, unique run id (uuid4 hex). Not security-sensitive — a correlation key."""
    return uuid.uuid4().hex[:12]


@contextlib.contextmanager
def run_context(incident_id: str, run_id: str) -> Iterator[str]:
    """Bind ``incident_id``/``run_id`` for the enclosed block; clear on exit."""
    with structlog.contextvars.bound_contextvars(
        incident_id=incident_id, run_id=run_id
    ):
        yield run_id


def current_ids() -> dict[str, str]:
    """The currently-bound correlation ids (empty outside a ``run_context``)."""
    ctx = structlog.contextvars.get_contextvars()
    return {k: ctx[k] for k in ("incident_id", "run_id") if k in ctx}
