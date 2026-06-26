"""Tests for the LLM-judge (Wave 2) -- offline, scripted fake provider."""

from __future__ import annotations

import json
from pathlib import Path

from evals.llm_judge import default_judge_provider, llm_judge
from evals.scenarios.generator import load_scenario
from quellgeist.agent.schema import Diagnosis, Hypothesis

SCENARIO = load_scenario(
    Path(__file__).parents[2]
    / "evals"
    / "scenarios"
    / "fixtures"
    / "bad_deploy_0001.json"
)


class FakeProvider:
    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    def complete(self, messages):
        self.messages = messages
        return self.reply


def _diag():
    return Diagnosis(
        summary="s",
        hypotheses=[
            Hypothesis(
                cause="bad deploy a1b2c3d broke auth.verify_token",
                confidence=0.9,
                evidence=[{"type": "commit", "sha": "a1b2c3d"}],
            )
        ],
    )


def test_rubric_is_parsed():
    reply = json.dumps(
        {
            "correct_cause": True,
            "evidence_valid": True,
            "actions_sensible": False,
            "score": 0.8,
            "reason": "right cause, weak actions",
        }
    )
    v = llm_judge(_diag(), SCENARIO, FakeProvider(reply))
    assert v.correct_cause and v.evidence_valid and not v.actions_sensible
    assert v.score == 0.8 and v.parsed
    assert v.passed  # correct_cause and evidence_valid


def test_score_is_clamped_to_unit_interval():
    v = llm_judge(
        _diag(),
        SCENARIO,
        FakeProvider(
            json.dumps({"correct_cause": True, "evidence_valid": True, "score": 5})
        ),
    )
    assert v.score == 1.0


def test_unparseable_reply_scores_zero_and_fails():
    v = llm_judge(_diag(), SCENARIO, FakeProvider("sorry, I cannot grade this"))
    assert not v.parsed and v.score == 0.0 and not v.passed


def test_gold_cause_is_passed_to_the_judge():
    fp = FakeProvider(
        json.dumps({"correct_cause": True, "evidence_valid": True, "score": 1})
    )
    llm_judge(_diag(), SCENARIO, fp)
    user = fp.messages[-1]["content"]
    assert "gold_cause" in user and SCENARIO.id in user


def test_judge_model_config_knob(monkeypatch):
    monkeypatch.setenv("QG_JUDGE_MODEL", "gemini/gemini-2.5-pro")
    assert default_judge_provider().model == "gemini/gemini-2.5-pro"
