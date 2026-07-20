"""Timing-aware verifier probe set (Wave 10, T10.1; DR-0024).

The culprit-after-errors class the DETERMINISTIC timing verifier
(``quellgeist.agent.timing_verifier``) is built to catch. Each probe is a
``time_shift`` scenario -- the only-candidate deploy postdates the errors it would
need to cause, reused verbatim from ``ABSTAIN_RECIPES`` so nothing is reinvented --
paired with the sha of that postdating culprit. That lets the check be exercised
against the exact adversarial diagnosis a support-only reviewer can be talked into
confirming: "the newest deploy broke it", citing a commit that came AFTER the
incident began.

Keyless by construction: ``timing_abstains`` needs no model -- it asks whether the
timing verifier forces abstention when a diagnosis cites the postdating culprit.
Recall over this set is the T10.1 acceptance number, reportable on the keyless gate.
A model run MAY also use these scenarios to measure how often the reasoner itself is
fooled (the number the verifier then backstops), but that is out-of-band.

Draws only the ``probe`` split (fixtures vocabulary) and carries ``__time_shift``
ids via ``variant_scenario`` -- so every contamination check applies unchanged.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from evals.scenarios.generator import Scenario, generate_scenarios
from evals.training.trajectories import ABSTAIN_RECIPES, culprit_of
from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef
from quellgeist.agent.timing_verifier import verify_timing

_SEED = 20260720
_N = 8


@dataclass(frozen=True)
class TimingProbe:
    scenario: Scenario  # a time_shift variant: the culprit deploy postdates the errors
    culprit_sha: str  # the postdating commit a fooled reasoner would cite
    first_error_id: (
        int  # a real log handle to co-cite (keeps the hypothesis well-formed)
    )


def _commit_gold(s: Scenario) -> bool:
    return any(r.type == "commit" for r in s.gold_evidence_refs)


def build_timing_probes(n: int = _N) -> list[TimingProbe]:
    """Deterministically derive ``n`` culprit-after-errors probes from the probe
    split. Only commit-gold classes qualify (the timing claim is about a deploy)."""
    rng = random.Random(_SEED)
    pool = [s for s in generate_scenarios("probe") if _commit_gold(s)]
    if len(pool) < n:
        raise ValueError(
            f"probe split has only {len(pool)} commit-gold scenarios (<{n})"
        )
    probes: list[TimingProbe] = []
    for s in pool[:n]:
        culprit_sha = culprit_of(s)["sha"]
        shifted = ABSTAIN_RECIPES["time_shift"](s, rng)
        first_error_id = min(
            (r["id"] for r in shifted.logs if r["level"] == "ERROR"),
            default=shifted.logs[0]["id"],
        )
        probes.append(TimingProbe(shifted, culprit_sha, first_error_id))
    return probes


def fooled_diagnosis(probe: TimingProbe) -> Diagnosis:
    """The adversarial diagnosis a support-only reviewer can be talked into: it
    names the postdating culprit as the cause and cites it (plus a real error log)."""
    return Diagnosis(
        summary="the most recent deploy looks responsible",
        hypotheses=[
            Hypothesis(
                cause=f"deploy {probe.culprit_sha} broke the failing route",
                confidence=0.9,
                evidence=[
                    CommitRef(sha=probe.culprit_sha),
                    LogRef(id=probe.first_error_id),
                ],
            )
        ],
    )


def timing_abstains(probe: TimingProbe) -> bool:
    """True iff the timing verifier forces abstention on the fooled diagnosis -- the
    keyless T10.1 acceptance signal for a single probe."""
    res = verify_timing(
        fooled_diagnosis(probe), probe.scenario.logs, probe.scenario.commits
    )
    return res.diagnosis.abstained
