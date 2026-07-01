"""Tests for the judge-validation harness (Wave 3, DR-0018). Offline -- no model.

The harness measures whether the advisory LLM-judge AGREES with human labels on a
hand-labelled subset. These tests drive it with scripted fake judges so the
agreement math (overall, per-field, Cohen's kappa) and the skip behaviour are
exercised without any model call.
"""

from __future__ import annotations

import json

import pytest
from litellm.exceptions import AuthenticationError, RateLimitError

from evals.validate_judge import (
    cohen_kappa,
    load_cases,
    main,
    run_validation,
)

CASES = load_cases()


def _rubric(correct_cause, evidence_valid, score=None):
    return json.dumps(
        {
            "correct_cause": correct_cause,
            "evidence_valid": evidence_valid,
            "actions_sensible": True,
            "score": (
                score
                if score is not None
                else (1.0 if correct_cause and evidence_valid else 0.0)
            ),
        }
    )


class ScriptedJudge:
    """Returns one scripted rubric reply per case, in order."""

    model = "fake/judge"

    def __init__(self, replies):
        self.replies = list(replies)

    def complete(self, messages):
        return self.replies.pop(0)


def _echo(cases):
    return ScriptedJudge(
        [_rubric(c.human_correct_cause, c.human_evidence_valid) for c in cases]
    )


def test_cases_load_and_are_self_consistent():
    assert len(CASES) >= 9
    assert {c.scenario.failure_class for c in CASES} == {
        "bad_deploy",
        "config_error",
        "resource_exhaustion",
    }
    # verdict is exactly correct_cause AND evidence_valid, and both verdicts occur
    for c in CASES:
        assert c.human_pass == (c.human_correct_cause and c.human_evidence_valid)
    assert any(c.human_pass for c in CASES) and any(not c.human_pass for c in CASES)


def test_a_judge_that_matches_the_human_scores_perfect_agreement():
    report = run_validation(CASES, _echo(CASES))
    assert report.verdict_agreement == report.n
    assert report.cc_agreement == report.n
    assert report.ev_agreement == report.n
    assert report.kappa == 1.0
    assert report.disagreements == []


def test_a_judge_that_inverts_the_human_scores_below_chance():
    inverted = ScriptedJudge(
        [_rubric(not c.human_correct_cause, not c.human_evidence_valid) for c in CASES]
    )
    report = run_validation(CASES, inverted)
    assert report.kappa < 0  # worse than chance


def test_a_single_disagreement_is_reported():
    replies = [_rubric(c.human_correct_cause, c.human_evidence_valid) for c in CASES]
    # flip the judge's evidence_valid on the first case so its verdict disagrees
    first = CASES[0]
    replies[0] = _rubric(first.human_correct_cause, not first.human_evidence_valid)
    report = run_validation(CASES, ScriptedJudge(replies))
    ids = [r.case.id for r in report.disagreements]
    # flipping evidence_valid changes `passed` only if it flips cc AND ev result
    if first.human_pass != (
        first.human_correct_cause and not first.human_evidence_valid
    ):
        assert first.id in ids


def test_cohen_kappa_edges():
    assert cohen_kappa([True, False, True, False], [True, False, True, False]) == 1.0
    assert cohen_kappa([True, True, False, False], [True, False, True, False]) == 0.0
    assert cohen_kappa([], []) == 0.0


def test_main_offline_reports_and_returns_zero(capsys):
    assert main(provider=_echo(CASES)) == 0
    out = capsys.readouterr().out
    assert "verdict agreement" in out
    assert "Cohen's kappa" in out


class _Unavailable:
    model = "fake/unavailable"

    def complete(self, messages):
        raise RateLimitError(message="quota", llm_provider="groq", model="x")


def test_main_skips_when_judge_unavailable(capsys):
    assert main(provider=_Unavailable()) == 0
    assert "SKIPPED" in capsys.readouterr().err


class _BadKey:
    model = "fake/badkey"

    def complete(self, messages):
        raise AuthenticationError(message="bad key", llm_provider="groq", model="x")


def test_main_skips_on_invalid_credentials(capsys):
    assert main(provider=_BadKey()) == 0
    assert "credentials" in capsys.readouterr().err.lower()


def test_load_cases_rejects_nothing_valid():
    # every diagnosis and scenario in the file must parse (load_cases would raise)
    assert all(c.diagnosis is not None and c.scenario is not None for c in CASES)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
