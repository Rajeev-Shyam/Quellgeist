"""quellgeist.orchestrator — resumable investigation around the FROZEN loop. Wave 7 (T7.4).

Per [DR-0023](../../../docs/quellgeist-adr-log.md) decisions 5 & 6. This is the only
place that knows about hints, the review gate, and resolution re-check — and it calls
``agent.loop.run_loop`` **unchanged**. ``incident_tools`` builds concurrency-safe tool
closures bound to a per-incident snapshot dir (no process-global env), so parallel
investigations never cross-read signals.

Wave 7 ships ``investigate`` (run → fabrication check → persist → ``pending_review``).
``resume_after_review`` (Wave 8) and ``verify_resolution`` (Wave 9) wrap the same call.
"""

from __future__ import annotations

from quellgeist.orchestrator.investigate import InvestigationResult, investigate
from quellgeist.orchestrator.resolution import (
    ResolutionError,
    ResolutionVerdict,
    verify_resolution,
)
from quellgeist.orchestrator.tools_factory import incident_tools, read_signals

__all__ = [
    "InvestigationResult",
    "ResolutionError",
    "ResolutionVerdict",
    "incident_tools",
    "investigate",
    "read_signals",
    "verify_resolution",
]
