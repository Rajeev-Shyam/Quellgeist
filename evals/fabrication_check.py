"""Deterministic fabrication check (Wave 2).

The headline reliability guarantee made real: every evidence handle a Diagnosis
cites must resolve to a signal the scenario actually contains. This is a pure
set-membership lookup over the FULL signal set (all log ids + all commit shas),
NOT the run-scoped ``cited_but_unseen`` proxy the Wave-1 loop records -- that
proxy over-flags real-but-unqueried ids (DR-0009). Existence is checked here;
whether the evidence *supports* the claim is the verifier's job, and overall
quality is the judge's.

The check is **fail-closed**: a cited handle whose ``(type, key)`` is absent from
the real-signal set is a fabrication. As of Wave 3 the signal set includes metric
series ids, so a legitimate ``MetricRef`` resolves; a cited metric that no series
provides is still a fabrication (DR-0009 watch-out: prefer fail-closed over
fail-open on unknown ref types).

The implementation was relocated into the installed package
(``quellgeist.agent.citations``, DR-0021) so ``quellgeist diagnose`` can enforce
the same guarantee on live incidents. This module re-exports it verbatim, so the
eval harness and its tests are byte-identical.
"""

from __future__ import annotations

from quellgeist.agent.citations import (
    FabricationError,
    FabricationResult,
    Handle,
    assert_no_fabrication,
    check_fabrication,
    cited_handles,
    real_signal_handles,
)

__all__ = [
    "FabricationError",
    "FabricationResult",
    "Handle",
    "assert_no_fabrication",
    "check_fabrication",
    "cited_handles",
    "real_signal_handles",
]
