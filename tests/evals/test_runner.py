"""Tests for the eval harness (Wave 1, Task 9). Offline -- scripted fake provider."""

from __future__ import annotations

import json
from pathlib import Path

from evals.run_evals import run_scenario
from evals.scenarios.generator import load_scenario

FIXTURE = (
    Path(__file__).parents[2]
    / "evals"
    / "scenarios"
    / "fixtures"
    / "bad_deploy_0001.json"
)


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _diagnose(cause, evidence):
    return json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "s",
                "abstained": False,
                "hypotheses": [
                    {"cause": cause, "confidence": 0.9, "evidence": evidence}
                ],
            },
        }
    )


def test_correct_diagnosis_passes():
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            _diagnose(
                "bad deploy a1b2c3d broke auth.verify_token",
                [
                    {"type": "log", "id": 2, "note": "first 500"},
                    {"type": "commit", "sha": "a1b2c3d"},
                ],
            ),
        ]
    )
    result = run_scenario(scenario, provider)
    assert result.judge.passed
    assert result.judge.correct_cause
    assert result.judge.evidence_matches


def test_wrong_cause_fails():
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [_diagnose("database connection pool exhausted", [{"type": "log", "id": 2}])]
    )
    result = run_scenario(scenario, provider)
    assert not result.judge.passed
    assert not result.judge.correct_cause


def test_abstention_fails_the_eval():
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "action": "diagnose",
                    "diagnosis": {
                        "abstained": True,
                        "abstention_reason": "weak",
                        "hypotheses": [],
                    },
                }
            )
        ]
    )
    result = run_scenario(scenario, provider)
    assert not result.judge.passed
    assert "abstained" in result.judge.reason


def test_loader_parses_gold_refs():
    scenario = load_scenario(FIXTURE)
    assert scenario.id == "bad_deploy_0001"
    assert {r.type for r in scenario.gold_evidence_refs} == {"log", "commit"}
