"""Cost capture: summarise a provider's per-call usage (Wave 7, T7.2).

The provider already records one ``CallUsage`` per completed model call in memory
(``agent/providers.py``, unchanged). Observability reads that list AFTER a run and
sums it — measured cost, not estimates — so nothing about the measured provider path
changes. A token field is ``None`` when the backend did not report it; those are
skipped, and the sum is ``None`` only if no call reported that field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class _HasCalls(Protocol):
    calls: list


@dataclass(frozen=True)
class UsageSummary:
    calls: int
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_s: float


def summarize_usage(provider: _HasCalls) -> UsageSummary:
    """Sum the provider's ``CallUsage`` records into one per-run summary."""
    calls = list(getattr(provider, "calls", []) or [])

    def _sum(attr: str) -> int | None:
        vals = [getattr(c, attr) for c in calls if getattr(c, attr, None) is not None]
        return sum(vals) if vals else None

    latency = sum(getattr(c, "latency_s", 0.0) or 0.0 for c in calls)
    return UsageSummary(
        calls=len(calls),
        prompt_tokens=_sum("prompt_tokens"),
        completion_tokens=_sum("completion_tokens"),
        latency_s=latency,
    )
