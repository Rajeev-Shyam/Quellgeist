"""quellgeist.observability — correlation ids + structured logs + cost. SCAFFOLD (Wave 7, T7.2).

Not yet implemented. Per [DR-0023](../../../docs/quellgeist-adr-log.md) decision 3
and the [v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. Self-observability
is a v2 requirement; this threads a per-incident/per-run id through a run and persists
its `CallUsage` cost — **without editing `agent/providers.py`'s measured behaviour**
(it reads the provider's existing in-memory `CallUsage` list after the run).

Planned surface:
- ``run_context(incident_id) -> contextmanager`` — binds ``run_id`` + ``incident_id``
  into a ``contextvars``-backed structlog context.
- ``summarize_usage(provider) -> UsageSummary`` — sums the provider's ``CallUsage``.
- ``attach(run_record, usage)``.

Depends on ``structlog`` (already a dep) and ``agent.providers.CallUsage`` (read-only).
"""

from __future__ import annotations

__all__: list[str] = []
