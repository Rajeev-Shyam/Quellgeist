"""Tests for the deterministic fabrication check (Wave 2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.fabrication_check import (
    FabricationError,
    assert_no_fabrication,
    check_fabrication,
    real_signal_handles,
)
from evals.scenarios.generator import load_scenario
from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis, LogRef, MetricRef

FIXTURE = (
    Path(__file__).parents[2]
    / "evals"
    / "scenarios"
    / "fixtures"
    / "bad_deploy_0001.json"
)
SCENARIO = load_scenario(FIXTURE)


def _diag(evidence) -> Diagnosis:
    return Diagnosis(
        summary="s",
        hypotheses=[
            Hypothesis(cause="deploy a1b2c3d", confidence=0.9, evidence=evidence)
        ],
    )


def _check(diagnosis: Diagnosis):
    return check_fabrication(diagnosis, SCENARIO.logs, SCENARIO.commits)


def test_real_signal_handles_covers_all_ids_and_shas():
    handles = real_signal_handles(SCENARIO.logs, SCENARIO.commits)
    assert ("log", 2) in handles
    assert ("commit", "a1b2c3d") in handles
    assert ("commit", "9f8e7d6") in handles
    # every fixture log id 0..5 and both shas, nothing else
    assert handles == {("log", i) for i in range(6)} | {
        ("commit", "a1b2c3d"),
        ("commit", "9f8e7d6"),
    }


def test_clean_diagnosis_has_no_fabrication():
    d = _diag([LogRef(id=2, note="first 500"), CommitRef(sha="a1b2c3d")])
    result = _check(d)
    assert result.ok
    assert result.fabricated == frozenset()


def test_fabricated_log_id_is_flagged():
    d = _diag([LogRef(id=999, note="invented")])
    result = _check(d)
    assert not result.ok
    assert ("log", 999) in result.fabricated


def test_fabricated_sha_is_flagged():
    d = _diag([CommitRef(sha="deadbee")])
    result = _check(d)
    assert ("commit", "deadbee") in result.fabricated


def test_partial_fabrication_flags_only_the_fake():
    d = _diag([LogRef(id=2), LogRef(id=999), CommitRef(sha="a1b2c3d")])
    result = _check(d)
    assert result.fabricated == frozenset({("log", 999)})  # real ones not flagged


def test_abstained_diagnosis_is_vacuously_clean():
    d = Diagnosis(abstained=True, abstention_reason="signals too weak", hypotheses=[])
    assert _check(d).ok


def test_metric_handle_fails_closed_when_no_metrics_present():
    # A scenario with no metric series (the log+commit classes): a cited metric
    # handle resolves to nothing and is fabricated (fail-closed, DR-0009).
    d = _diag([MetricRef(id="cpu.usage")])
    result = _check(d)
    assert ("metric", "cpu.usage") in result.fabricated


_METRICS = [{"metric": "db_connections_in_use", "unit": "count", "points": []}]


def test_real_signal_handles_includes_metric_series():
    handles = real_signal_handles(SCENARIO.logs, SCENARIO.commits, _METRICS)
    assert ("metric", "db_connections_in_use") in handles


def test_cited_metric_resolves_when_the_series_exists():
    d = _diag([MetricRef(id="db_connections_in_use"), CommitRef(sha="a1b2c3d")])
    result = check_fabrication(d, SCENARIO.logs, SCENARIO.commits, _METRICS)
    assert result.ok


def test_unknown_metric_fails_closed_even_with_metrics_present():
    d = _diag([MetricRef(id="not_a_real_metric")])
    result = check_fabrication(d, SCENARIO.logs, SCENARIO.commits, _METRICS)
    assert ("metric", "not_a_real_metric") in result.fabricated


def test_assert_raises_on_fabrication_with_message():
    d = _diag([LogRef(id=999), CommitRef(sha="a1b2c3d")])
    with pytest.raises(FabricationError) as exc:
        assert_no_fabrication(d, SCENARIO.logs, SCENARIO.commits)
    assert "log:999" in str(exc.value)
    assert "a1b2c3d" not in str(exc.value)  # the real one isn't reported


def test_assert_passes_on_clean_diagnosis():
    d = _diag([LogRef(id=2), CommitRef(sha="a1b2c3d")])
    assert_no_fabrication(d, SCENARIO.logs, SCENARIO.commits)  # no raise
