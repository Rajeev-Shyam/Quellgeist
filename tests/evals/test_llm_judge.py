"""Tests for the LLM-judge stub (Wave 2). Logic deferred -- see DR-0014."""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.llm_judge import default_judge_provider, llm_judge
from evals.scenarios.generator import load_scenario
from quellgeist.agent.schema import Diagnosis

SCENARIO = load_scenario(
    Path(__file__).parents[2]
    / "evals"
    / "scenarios"
    / "fixtures"
    / "bad_deploy_0001.json"
)


def test_llm_judge_is_not_implemented_yet():
    d = Diagnosis(abstained=True, abstention_reason="x", hypotheses=[])
    with pytest.raises(NotImplementedError, match="gold subset"):
        llm_judge(d, SCENARIO, object())


def test_judge_model_config_knob_reads_env(monkeypatch):
    monkeypatch.setenv("QG_JUDGE_MODEL", "gemini/gemini-2.5-pro")
    assert default_judge_provider().model == "gemini/gemini-2.5-pro"
