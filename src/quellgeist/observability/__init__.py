"""quellgeist.observability — correlation ids + structured logs + cost. Wave 7 (T7.2).

Self-observability (DR-0023 decision 3): ``run_context`` binds a per-incident/per-run
id into structlog for the duration of a run; ``configure_logging`` installs the JSON
pipeline; ``summarize_usage`` sums the provider's existing in-memory ``CallUsage``
records into a per-run cost — all **without editing** ``agent/providers.py``'s measured
behaviour. The store persists the summary + trace; there is no live dashboard (Q16).
"""

from __future__ import annotations

from quellgeist.observability.context import (
    current_ids,
    new_run_id,
    run_context,
)
from quellgeist.observability.logging import configure_logging, get_logger
from quellgeist.observability.usage import UsageSummary, summarize_usage

__all__ = [
    "UsageSummary",
    "configure_logging",
    "current_ids",
    "get_logger",
    "new_run_id",
    "run_context",
    "summarize_usage",
]
