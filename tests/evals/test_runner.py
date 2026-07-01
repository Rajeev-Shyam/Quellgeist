"""Tests for the eval harness (Wave 1, Task 9). Offline -- scripted fake provider."""

from __future__ import annotations

import json
from pathlib import Path

from litellm.exceptions import AuthenticationError, RateLimitError

import evals.run_evals as run_evals
from evals.run_evals import main, run_all, run_scenario
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


def test_correct_cause_via_citation_not_prose():
    """Regression (DR-0017): a correct diagnosis that cites the gold commit as a
    structured handle but does NOT repeat the sha in the prose must score
    correct_cause=True. The first real eval run produced exactly this, and the old
    `sha in cause_text` check false-failed it."""
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [
            _diagnose(
                "A recent deploy refactored token parsing and broke "
                "auth.verify_token on a NoneType -- no sha in this sentence",
                [{"type": "log", "id": 2}, {"type": "commit", "sha": "a1b2c3d"}],
            )
        ]
    )
    result = run_scenario(scenario, provider)
    assert result.judge.correct_cause  # pinned the gold commit via its handle
    assert result.judge.passed


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


_CORRECT_SCRIPT = [
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


class GoldProvider:
    """Emits, per scenario in main()'s sorted load order, the gold-correct
    exchange (query ERROR logs -> list commits -> diagnose citing that scenario's
    gold cause + evidence handles). Lets the offline entry-point smoke exercise
    the FULL generated corpus, not just one hand-scripted fixture."""

    def __init__(self, scenarios):
        self.scripted = []
        for s in scenarios:
            evidence = [
                (
                    {"type": "commit", "sha": r.sha}
                    if r.type == "commit"
                    else {"type": r.type, "id": r.id}  # log or metric
                )
                for r in s.gold_evidence_refs
            ]
            self.scripted += [
                json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
                json.dumps({"action": "get_recent_commits", "args": {}}),
                _diagnose(s.gold_cause, evidence),
            ]

    def complete(self, messages):
        return self.scripted.pop(0)


def test_clean_correct_scenario_has_no_fabrication():
    scenario = load_scenario(FIXTURE)
    result = run_scenario(scenario, FakeProvider(list(_CORRECT_SCRIPT)))
    assert result.fabrication.ok
    assert result.passed  # judge passes AND nothing fabricated


def test_fabricated_handle_fails_scenario_despite_correct_judge():
    """Cites the gold evidence (so the judge passes) PLUS a nonexistent id --
    the zero-fabrication bar must still fail the scenario."""
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            _diagnose(
                "bad deploy a1b2c3d broke auth.verify_token",
                [
                    {"type": "log", "id": 2},
                    {"type": "commit", "sha": "a1b2c3d"},
                    {"type": "log", "id": 999, "note": "invented"},
                ],
            ),
        ]
    )
    result = run_scenario(scenario, provider)
    assert result.judge.passed  # gold cited + correct cause
    assert not result.fabrication.ok
    assert ("log", 999) in result.fabrication.fabricated
    assert not result.passed  # ... but the fabrication fails the scenario


def test_run_all_returns_zero_on_clean_pass(capsys):
    scenario = load_scenario(FIXTURE)
    rc = run_all([scenario], FakeProvider(list(_CORRECT_SCRIPT)))
    out = capsys.readouterr().out
    assert rc == 0
    assert "1/1 scenarios passed; 0 with fabricated evidence" in out


def test_run_all_returns_one_on_fabrication(capsys):
    scenario = load_scenario(FIXTURE)
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            _diagnose(
                "bad deploy a1b2c3d broke auth.verify_token",
                [{"type": "log", "id": 2}, {"type": "log", "id": 999}],
            ),
        ]
    )
    rc = run_all([scenario], provider)
    out = capsys.readouterr().out
    assert rc == 1
    assert "1 with fabricated evidence" in out


def test_main_offline_returns_zero(monkeypatch):
    # main() globs ALL fixtures and builds a real provider; swap in a gold-aware
    # fake that answers each scenario correctly from its own gold, so the entry
    # point is exercised end-to-end over the whole corpus with no model/network.
    scenarios = run_evals._load_all_fixtures()
    monkeypatch.setattr(run_evals, "LiteLLMProvider", lambda: GoldProvider(scenarios))
    assert main() == 0


class _UnavailableProvider:
    """A backend that can't be reached (walled free-tier key 429s past retries)."""

    def complete(self, messages):
        raise RateLimitError(
            message="quota exhausted", llm_provider="gemini", model="gemini/x"
        )


def test_main_skips_when_backend_unavailable(capsys):
    # A present-but-quota-walled key must SKIP (exit 0), not redden CI: an
    # unreachable model is not a reliability failure (DR-0012).
    rc = main(provider=_UnavailableProvider())
    assert rc == 0
    assert "SKIPPED" in capsys.readouterr().err


class _BadKeyProvider:
    """A backend that rejects the credentials (stale / invalid / rotated key)."""

    def complete(self, messages):
        raise AuthenticationError(
            message="API key not valid", llm_provider="gemini", model="gemini/x"
        )


def test_main_skips_on_invalid_credentials(capsys):
    # A stale/invalid key (e.g. a rotated CI secret) must SKIP (exit 0), not
    # redden the non-gating reporting job -- it's a config problem, not an eval
    # failure (DR-0017).
    rc = main(provider=_BadKeyProvider())
    assert rc == 0
    assert "credentials" in capsys.readouterr().err.lower()


def test_verifier_pass_can_force_abstention_in_eval():
    # The reasoner proposes the correct cause; the verifier rejects its evidence
    # -> forced abstention -> the keyword judge fails the scenario.
    scenario = load_scenario(FIXTURE)
    reasoner = FakeProvider(list(_CORRECT_SCRIPT))
    verifier = FakeProvider([json.dumps({"supported": False, "reason": "unrelated"})])
    r = run_scenario(scenario, reasoner, verifier_provider=verifier)
    assert r.verifier is not None and r.verifier.forced_abstention
    assert not r.passed


def test_judge_provider_populates_advisory_rubric():
    # The LLM-judge rubric is recorded but does NOT change the deterministic gate.
    scenario = load_scenario(FIXTURE)
    reasoner = FakeProvider(list(_CORRECT_SCRIPT))
    judgep = FakeProvider(
        [
            json.dumps(
                {
                    "correct_cause": True,
                    "evidence_valid": True,
                    "actions_sensible": True,
                    "score": 0.9,
                }
            )
        ]
    )
    r = run_scenario(scenario, reasoner, judge_provider=judgep)
    assert r.rubric is not None and r.rubric.passed and r.rubric.score == 0.9
    assert r.passed  # the keyword judge + fabrication gate still decides
