"""Deterministic citation / fabrication check (Wave 2 core, relocated in v1.1).

The headline reliability guarantee, made real: every evidence handle a Diagnosis
cites must resolve to a signal the incident actually contains. This is a pure
set-membership lookup over the FULL signal set (all log ids + all commit shas +
all metric-series names), fail-closed and keyless -- no model needed.

It originally lived in ``evals/fabrication_check.py`` (the eval harness). It is
relocated here, inside the *installed package*, so the same guarantee runs at the
point of real use -- ``quellgeist diagnose`` on a live incident -- not only in the
repo-only eval suite (``evals/`` is not shipped in the wheel). ``evals`` re-exports
these names, so the frozen eval path is byte-identical (DR-0022).

Existence is checked here; whether the evidence *supports* the claim is the
verifier's job, and overall quality is the judge's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from quellgeist.agent.schema import Diagnosis

Handle = tuple[str, Any]


def real_signal_handles(
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    metrics: list[dict[str, Any]] | None = None,
) -> set[Handle]:
    """Every handle a diagnosis is allowed to cite for this incident: each log
    row's source-stable ``id``, each commit ``sha``, and each metric series'
    ``metric`` name, verbatim."""
    handles: set[Handle] = set()
    for row in logs:
        if "id" in row:
            handles.add(("log", row["id"]))
    for c in commits:
        if "sha" in c:
            handles.add(("commit", c["sha"]))
    for m in metrics or []:
        if "metric" in m:
            handles.add(("metric", m["metric"]))
    return handles


def cited_handles(diagnosis: Diagnosis) -> set[Handle]:
    """The set of handles cited across all hypotheses. An abstained diagnosis
    has no hypotheses, so it cites nothing."""
    return {ref.key for h in diagnosis.hypotheses for ref in h.evidence}


@dataclass(frozen=True)
class FabricationResult:
    fabricated: frozenset[Handle] = field(default_factory=frozenset)

    @property
    def ok(self) -> bool:
        return not self.fabricated


def check_fabrication(
    diagnosis: Diagnosis,
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    metrics: list[dict[str, Any]] | None = None,
) -> FabricationResult:
    """Cited handles that do NOT exist in the real signal set. ``ok`` when empty.
    An abstained diagnosis cites nothing, so it is vacuously clean."""
    real = real_signal_handles(logs, commits, metrics)
    return FabricationResult(frozenset(cited_handles(diagnosis) - real))


class FabricationError(AssertionError):
    """A non-abstained diagnosis cited evidence that does not exist in the
    real signals -- the failure mode the whole project exists to prevent."""


def assert_no_fabrication(
    diagnosis: Diagnosis,
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    metrics: list[dict[str, Any]] | None = None,
) -> None:
    """Raise ``FabricationError`` if any cited handle is absent from the real
    signals (fail-closed). No-op on a clean or abstained diagnosis."""
    result = check_fabrication(diagnosis, logs, commits, metrics)
    if not result.ok:
        joined = ", ".join(f"{t}:{k}" for t, k in sorted(result.fabricated))
        raise FabricationError(f"cited evidence not found in real signals: {joined}")
