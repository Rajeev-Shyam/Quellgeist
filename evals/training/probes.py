"""DR-0020 probe sets — built alongside the training data, never trained on.

Two instruments the pass rates cannot provide (DR-0020 decision 6):

- **Abstention probe** (12 ablated scenarios from the ``probe`` split): the
  eval judge auto-fails abstention, so neither eval corpus can see whether
  abstain-over-guess survived tuning. Run via
  ``python -m evals.training.run_abstention_probe`` — pass iff the (verified)
  diagnosis abstains. Acceptance: recall ≥ 90% over repeated passes.
- **Structure-perturbation probe** (10 still-solvable scenarios that break the
  corpus skeleton: a third commit, a culprit that is not the newest commit, a
  decoy touching code files, a multi-route burst): the script-vs-policy
  diagnostic. Reported, never gated — fixtures and holdout share the skeleton,
  so this is the only instrument that can tell a memorised positional script
  from a learned policy. Runnable as a normal eval set:
  ``QG_SCENARIOS_DIR=evals/training/probes/structure``.

Both draw only fixtures-bank vocabulary (the ``probe`` split, seed 20260704)
and carry ``probe_`` ids, so every contamination check applies unchanged.
"""

from __future__ import annotations

import random
from datetime import timedelta

from evals.scenarios.generator import Scenario, generate_scenarios
from evals.training.trajectories import (
    ABSTAIN_RECIPES,
    culprit_of,
    error_rows,
    fmt_ts,
    parse_ts,
    take_scenarios,
    variant_scenario,
)

_SEED = 20260706
_HEX = "0123456789abcdef"

# recipe -> count; weak_link is bad_deploy-only (see its docstring in
# trajectories.py). Hard variants dominate, mirroring the training abstain mix.
_ABSTENTION_PROBE = {
    "no_culprit": 2,
    "no_incident": 2,
    "time_shift": 3,
    "weak_link": 3,
    "decoy_wall": 2,
}
_STRUCTURE_PROBE = {
    "third_commit": 3,
    "culprit_not_newest": 3,
    "decoy_code_files": 2,
    "multi_route": 2,
}


def _new_sha(rng: random.Random, exclude: frozenset[str]) -> str:
    while True:
        sha = "".join(rng.choice(_HEX) for _ in range(7))
        if sha not in exclude:
            return sha


# --------------------------------------------------------------------------- #
# Structure recipes — every result stays GOLD-SOLVABLE (unchanged gold refs);
# what breaks is the skeleton regularity a positional script relies on.
# --------------------------------------------------------------------------- #


def _third_commit(s: Scenario, rng: random.Random) -> Scenario:
    """A third innocent commit between the decoy and the culprit."""
    culprit = culprit_of(s)
    extra = {
        "sha": _new_sha(rng, frozenset(c["sha"] for c in s.commits)),
        "ts": fmt_ts(parse_ts(culprit["ts"]) - timedelta(minutes=30)),
        "msg": "test: add coverage for utils",
        "files": ["tests/test_utils.py"],
    }
    return variant_scenario(s, "third_commit", commits=s.commits + [extra])


def _culprit_not_newest(s: Scenario, rng: random.Random) -> Scenario:
    """An innocent docs commit NEWER than the culprit — 'cite the newest
    commit' now fails the judge, which is the point."""
    first_err = error_rows(s)[0]
    extra = {
        "sha": _new_sha(rng, frozenset(c["sha"] for c in s.commits)),
        "ts": fmt_ts(parse_ts(first_err["ts"]) + timedelta(seconds=60)),
        "msg": "docs: update README",
        "files": ["README.md"],
    }
    return variant_scenario(s, "culprit_not_newest", commits=s.commits + [extra])


def _decoy_code_files(s: Scenario, rng: random.Random) -> Scenario:
    """The decoy touches a code file instead of README.md — 'the decoy is the
    README commit' stops being a usable feature."""
    culprit_sha = culprit_of(s)["sha"]
    commits = [
        (
            {**c, "msg": "style: reformat imports", "files": ["demo/app/utils.py"]}
            if c["sha"] != culprit_sha
            else c
        )
        for c in s.commits
    ]
    return variant_scenario(s, "decoy_code_files", commits=commits)


def _multi_route(s: Scenario, rng: random.Random) -> Scenario:
    """The error burst spreads to a second route (same signature, same cause)
    — 'exactly one error route' stops holding. Appended rows keep source-stable
    ids past the existing range, so the gold log handle is untouched."""
    routes = sorted({r["route"] for r in s.logs})
    errs = error_rows(s)
    other = next(rt for rt in routes if rt != errs[0]["route"])
    next_id = max(r["id"] for r in s.logs) + 1
    spread = [
        {
            "id": next_id + i,
            "ts": fmt_ts(parse_ts(row["ts"]) + timedelta(seconds=7)),
            "level": "ERROR",
            "route": other,
            "status": 500,
            "msg": row["msg"],
        }
        for i, row in enumerate(errs)
    ]
    merged = sorted(s.logs + spread, key=lambda r: r["ts"])
    return variant_scenario(s, "multi_route", logs=merged)


_STRUCTURE_RECIPES = {
    "third_commit": _third_commit,
    "culprit_not_newest": _culprit_not_newest,
    "decoy_code_files": _decoy_code_files,
    "multi_route": _multi_route,
}


def build_probes() -> tuple[list[Scenario], list[Scenario]]:
    """Deterministically derive both probe sets from the ``probe`` split."""
    rng = random.Random(_SEED)
    pool = list(generate_scenarios("probe"))
    rng.shuffle(pool)

    abstention: list[Scenario] = []
    for recipe, n in _ABSTENTION_PROBE.items():
        only = "bad_deploy" if recipe == "weak_link" else None
        for s in take_scenarios(pool, n, only=only):
            ablated = ABSTAIN_RECIPES[recipe](s, rng)
            doc = ablated.model_dump()
            # an unanswerable item carries no gold handles — self-documenting,
            # and nothing downstream can mistake it for a solvable eval item.
            doc["gold_cause"] = f"unanswerable ({recipe}): a correct diagnosis abstains"
            doc["gold_evidence_refs"] = []
            abstention.append(Scenario(**doc))

    structure = [
        _STRUCTURE_RECIPES[recipe](s, rng)
        for recipe, n in _STRUCTURE_PROBE.items()
        for s in take_scenarios(pool, n)
    ]
    return abstention, structure
