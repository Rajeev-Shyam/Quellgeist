"""Tests for parameterised scenario generation (Wave 3). Deterministic, no model.

The load-bearing guarantee: every generated scenario is a VALID eval item -- a
gold diagnosis built from its own ``gold_cause`` + ``gold_evidence_refs`` passes
the deterministic judge AND cites no fabricated evidence. Plus the fixtures and
holdout splits are drawn from disjoint distributions (DR-0003).
"""

from __future__ import annotations

import re

import pytest

from evals.fabrication_check import check_fabrication
from evals.judge import judge
from evals.scenarios.generator import (
    Scenario,
    distribution_tokens,
    generate_scenarios,
)
from quellgeist.agent.schema import Diagnosis, Hypothesis

# train/probe (DR-0020) flow through the same generator, so the per-split
# invariants (determinism, canonical timestamps, gold consistency,
# well-formedness) must hold for them too — the training corpus and probe
# sets are byte-derived from these scenarios.
_SPLITS = ("fixtures", "holdout", "train", "probe")
_CANONICAL_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _gold(scenario: Scenario) -> Diagnosis:
    """The diagnosis a perfect reasoner would emit for this scenario."""
    return Diagnosis(
        hypotheses=[
            Hypothesis(
                cause=scenario.gold_cause,
                confidence=1.0,
                evidence=scenario.gold_evidence_refs,
            )
        ]
    )


@pytest.mark.parametrize("split", _SPLITS)
def test_generation_is_deterministic(split):
    a = generate_scenarios(split)
    b = generate_scenarios(split)
    assert [s.model_dump() for s in a] == [s.model_dump() for s in b]


@pytest.mark.parametrize("split", _SPLITS)
def test_scenarios_use_canonical_timestamps(split):
    # `filters._require_canonical_ts` rejects non-canonical `since`, so every ts a
    # generated scenario carries must be the zero-padded %Y-%m-%dT%H:%M:%SZ form.
    for s in generate_scenarios(split):
        assert _CANONICAL_TS.match(s.now), s.now
        for row in s.logs:
            assert _CANONICAL_TS.match(row["ts"]), row
        for commit in s.commits:
            assert _CANONICAL_TS.match(commit["ts"]), commit


@pytest.mark.parametrize("split", _SPLITS)
def test_every_scenario_is_gold_consistent(split):
    # The core guard: a gold diagnosis must pass the deterministic judge AND
    # fabricate nothing -- i.e. each generated item is solvable and cites only
    # real signals. A scenario that failed this would silently poison the eval.
    for s in generate_scenarios(split):
        gold = _gold(s)
        assert judge(gold, s).passed, f"{s.id}: gold diagnosis does not pass the judge"
        assert check_fabrication(
            gold, s.logs, s.commits, s.metrics
        ).ok, f"{s.id}: gold evidence not found in the real signals"


@pytest.mark.parametrize("split", _SPLITS)
def test_scenarios_are_well_formed(split):
    for s in generate_scenarios(split):
        assert s.failure_class in {"bad_deploy", "config_error", "resource_exhaustion"}
        assert s.logs and s.commits and s.gold_cause
        assert any(row["level"] == "ERROR" for row in s.logs)
        log_ids = [row["id"] for row in s.logs]
        assert log_ids == list(range(len(log_ids)))  # stable 0..N-1 source ids
        shas = [c["sha"] for c in s.commits]
        assert len(shas) == len(set(shas))  # unique commit shas within a scenario
        # Only resource incidents carry metrics; when they do, the gold cites the
        # series (so a correct diagnosis MUST read metrics), and the metric ids in
        # the gold refs resolve to real series.
        if s.failure_class == "resource_exhaustion":
            assert s.metrics, f"{s.id}: resource scenario has no metric series"
            metric_names = {m["metric"] for m in s.metrics}
            gold_metrics = {r.id for r in s.gold_evidence_refs if r.type == "metric"}
            assert gold_metrics and gold_metrics <= metric_names
        else:
            assert s.metrics == []


def test_fixtures_and_holdout_are_disjoint_distributions():
    # DR-0003: the held-out set must come from a DIFFERENT distribution than the
    # fixtures, or eval numbers measure memorisation rather than skill.
    assert distribution_tokens("fixtures").isdisjoint(distribution_tokens("holdout"))


def test_expected_counts_classes_and_unique_ids():
    fixtures = generate_scenarios("fixtures")
    holdout = generate_scenarios("holdout")
    assert len(fixtures) == 64  # + the hand-authored bad_deploy_0001 anchor = 65
    assert len(holdout) == 16
    three = {"bad_deploy", "config_error", "resource_exhaustion"}
    for corpus in (fixtures, holdout):
        assert {s.failure_class for s in corpus} == three
        ids = [s.id for s in corpus]
        assert len(ids) == len(set(ids))
    # ids are namespaced by split so the two corpora never collide on disk.
    assert all(s.id.startswith("hold_") for s in holdout)
    assert not any(s.id.startswith("hold_") for s in fixtures)


def test_unknown_split_raises():
    with pytest.raises(ValueError, match="unknown split"):
        generate_scenarios("nope")
