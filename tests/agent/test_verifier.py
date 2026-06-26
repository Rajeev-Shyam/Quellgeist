"""Tests for the verifier pass (Wave 2) -- offline, scripted fake provider."""

from __future__ import annotations

import json

from quellgeist.agent.schema import Diagnosis, Hypothesis
from quellgeist.agent.verifier import default_verifier_provider, verify

LOGS = [
    {
        "id": 2,
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "message": "NoneType has no attribute in auth.verify_token",
    }
]
COMMITS = [
    {"sha": "a1b2c3d", "msg": "refactor auth.verify_token", "files": ["auth.py"]}
]


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _verdict(supported, reason="because"):
    return json.dumps({"supported": supported, "reason": reason})


def _diag(cause, evidence):
    return Diagnosis(
        summary="s",
        hypotheses=[Hypothesis(cause=cause, confidence=0.9, evidence=evidence)],
    )


def test_supported_hypothesis_survives():
    d = _diag(
        "bad deploy a1b2c3d broke auth.verify_token",
        [{"type": "log", "id": 2}, {"type": "commit", "sha": "a1b2c3d"}],
    )
    res = verify(d, LOGS, COMMITS, FakeProvider([_verdict(True)]))
    assert not res.diagnosis.abstained
    assert len(res.diagnosis.hypotheses) == 1
    assert res.verdicts[0].supported


def test_unsupported_hypothesis_forces_abstention():
    d = _diag("database connection pool exhausted", [{"type": "log", "id": 2}])
    res = verify(d, LOGS, COMMITS, FakeProvider([_verdict(False, "log is about auth")]))
    assert res.diagnosis.abstained
    assert res.forced_abstention
    assert res.verdicts[0].supported is False


def test_one_of_two_hypotheses_dropped():
    d = Diagnosis(
        summary="s",
        hypotheses=[
            Hypothesis(
                cause="bad deploy a1b2c3d",
                confidence=0.9,
                evidence=[{"type": "commit", "sha": "a1b2c3d"}],
            ),
            Hypothesis(
                cause="database pool",
                confidence=0.5,
                evidence=[{"type": "log", "id": 2}],
            ),
        ],
    )
    res = verify(d, LOGS, COMMITS, FakeProvider([_verdict(True), _verdict(False)]))
    assert not res.diagnosis.abstained
    assert [h.cause for h in res.diagnosis.hypotheses] == ["bad deploy a1b2c3d"]
    assert res.dropped == ["database pool"]


def test_missing_evidence_short_circuits_without_a_model_call():
    # cites a nonexistent log id -> nothing resolves -> unsupported, and NO model
    # call is spent (the fake would IndexError if called).
    d = _diag("phantom cause", [{"type": "log", "id": 999}])
    res = verify(d, LOGS, COMMITS, FakeProvider([]))
    assert res.diagnosis.abstained
    assert "no cited evidence" in res.verdicts[0].reason


def test_abstained_diagnosis_passes_through_untouched():
    d = Diagnosis(abstained=True, abstention_reason="weak signals", hypotheses=[])
    res = verify(d, LOGS, COMMITS, FakeProvider([]))
    assert res.diagnosis.abstained
    assert res.verdicts == []
    assert not res.forced_abstention  # the verifier didn't force it


def test_unparseable_verdict_counts_as_unsupported():
    d = _diag("bad deploy a1b2c3d", [{"type": "commit", "sha": "a1b2c3d"}])
    res = verify(d, LOGS, COMMITS, FakeProvider(["not json at all"]))
    assert res.diagnosis.abstained
    assert not res.verdicts[0].supported


def test_verifier_model_config_knob(monkeypatch):
    monkeypatch.setenv("QG_VERIFIER_MODEL", "gemini/gemini-2.5-pro")
    assert default_verifier_provider().model == "gemini/gemini-2.5-pro"
