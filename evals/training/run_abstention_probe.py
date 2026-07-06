"""Run the DR-0020 abstention probe — the instrument the eval judge cannot be.

The judge auto-fails every abstention, so fixtures/holdout pass rates cannot
see whether abstain-over-guess survived tuning. This runner scores the probe's
ablated, unanswerable scenarios the other way around: a scenario PASSES iff
the model DELIBERATELY abstained — a forced abstention (the loop's
step-exhaustion fallback, or the verifier dropping every guessed hypothesis)
is not the model choosing to abstain and counts as a FAIL, so a fine-tune that
collapses into malformed output or confident guessing cannot score recall.

Acceptance (DR-0020 decision 6): abstain recall ≥ 90% over repeated passes —
local temp-0 decoding is not run-to-run deterministic (DR-0019) — with zero
fabrication throughout. The exit code applies the single-pass floor (recall
≥ 90% AND fabrication = 0); the real acceptance aggregates repeated passes.

Same conventions as ``evals.run_evals``: provider from ``QG_MODEL``, opt-in
verifier via ``QG_VERIFY=1``, and an unreachable/unauthenticated backend is a
SKIP, never a reliability failure (DR-0012). Pin ``QG_VERIFIER_MODEL``
explicitly for matrix cells — DR-0020 decision 8: the ``QG_MODEL`` fallback
would let the tuned model verify itself, and the runner warns loudly when it
detects that configuration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from evals.run_evals import run_scenario
from evals.scenarios.generator import load_scenario
from quellgeist.agent.loop import FALLBACK_ABSTENTION_PREFIXES
from quellgeist.agent.providers import (
    LiteLLMProvider,
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.agent.verifier import default_verifier_provider

PROBE_DIR = Path(__file__).parent / "probes" / "abstention"


def main(
    provider: Provider | None = None,
    *,
    verifier_provider: Provider | None = None,
) -> int:
    scenarios = [load_scenario(p) for p in sorted(PROBE_DIR.glob("*.json"))]
    if not scenarios:
        print(f"no probe scenarios found in {PROBE_DIR}", file=sys.stderr)
        return 1
    if verifier_provider is None and os.environ.get("QG_VERIFY") == "1":
        if not os.environ.get("QG_VERIFIER_MODEL"):
            print(
                "WARNING: QG_VERIFY=1 with QG_VERIFIER_MODEL unset — the "
                "verifier falls back to QG_MODEL, i.e. the reasoner verifies "
                "itself. Pin QG_VERIFIER_MODEL for any comparison-matrix cell "
                "(DR-0020 decision 8).",
                file=sys.stderr,
            )
        verifier_provider = default_verifier_provider()
    provider = provider or LiteLLMProvider()

    deliberate = forced = fabricating = 0
    try:
        for s in scenarios:
            r = run_scenario(s, provider, verifier_provider=verifier_provider)
            loop_diag = r.loop.diagnosis
            reason = loop_diag.abstention_reason or ""
            model_abstained = loop_diag.abstained and not reason.startswith(
                FALLBACK_ABSTENTION_PREFIXES
            )
            final = r.verifier.diagnosis if r.verifier is not None else loop_diag
            deliberate += model_abstained
            forced += final.abstained and not model_abstained
            fabricating += not r.fabrication.ok
            mark = "PASS" if model_abstained else "FAIL"
            note = "" if model_abstained else (", forced" if final.abstained else "")
            print(
                f"[{mark}] {s.id}: abstained={model_abstained}{note}, "
                f"fabrication_ok={r.fabrication.ok}"
            )
    except Exception as exc:
        if is_provider_unavailable(exc) or is_auth_error(exc):
            print(
                f"SKIPPED: model backend unavailable/unauthenticated "
                f"({type(exc).__name__}) — not a reliability failure (DR-0012).",
                file=sys.stderr,
            )
            return 0
        raise
    n = len(scenarios)
    recall = deliberate / n
    print(
        f"\nabstain recall {deliberate}/{n} (+{forced} forced, not counted); "
        f"{fabricating} with fabricated evidence"
    )
    # Single-pass floor of the DR-0020 acceptance bar; the true bar aggregates
    # repeated passes. Fabrication on an unanswerable scenario always fails.
    return 0 if fabricating == 0 and recall >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
