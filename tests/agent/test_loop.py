"""Tests for the agent loop (Wave 1, Task 6)."""

from __future__ import annotations

import json

from quellgeist.agent.loop import LoopResult, ToolSpec, run_loop
from quellgeist.agent.schema import Diagnosis

ERROR_ROWS = [
    {
        "id": 2,
        "ts": "2026-06-23T12:02:12Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "TypeError in auth.verify_token",
    },
    {
        "id": 3,
        "ts": "2026-06-23T12:03:05Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "TypeError in auth.verify_token",
    },
]
COMMITS = [
    {
        "sha": "a1b2c3d",
        "ts": "2026-06-23T12:01:50Z",
        "msg": "deploy: refactor token parsing",
        "files": ["demo/app/auth.py"],
    },
]

_VALID_DIAGNOSE = json.dumps(
    {
        "action": "diagnose",
        "diagnosis": {
            "summary": "bad deploy a1b2c3d broke /login",
            "abstained": False,
            "hypotheses": [
                {
                    "cause": "deploy a1b2c3d broke auth.verify_token",
                    "confidence": 0.9,
                    "evidence": [
                        {"type": "log", "id": 2, "note": "first 500"},
                        {"type": "commit", "sha": "a1b2c3d", "note": "touched auth.py"},
                    ],
                }
            ],
            "suggested_actions": ["roll back a1b2c3d"],
        },
    }
)


def _tools(log_calls=None):
    def query_logs(**kw):
        if log_calls is not None:
            log_calls.append(kw)
        return ERROR_ROWS

    def get_recent_commits(**kw):
        return COMMITS

    return [
        ToolSpec("query_logs", "filter structured logs", query_logs),
        ToolSpec("get_recent_commits", "list recent deploys", get_recent_commits),
    ]


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def test_loop_calls_logs_then_diagnoses():
    log_calls: list[dict] = []
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
            json.dumps({"action": "get_recent_commits", "args": {"limit": 5}}),
            _VALID_DIAGNOSE,
        ]
    )
    result = run_loop(provider, _tools(log_calls=log_calls), now="2026-06-23T12:05:00Z")

    assert isinstance(result, LoopResult)
    assert ("query_logs", {"level": "ERROR"}) in result.tool_calls
    assert log_calls == [{"level": "ERROR"}]
    assert isinstance(result.diagnosis, Diagnosis)
    assert result.diagnosis.abstained is False
    assert "a1b2c3d" in result.diagnosis.hypotheses[0].cause
    assert result.cited_but_unseen_handles() == set()


def test_schema_violation_then_recovery():
    bad = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "hypotheses": [
                    {
                        "cause": "c",
                        "confidence": 2.0,
                        "evidence": [{"type": "log", "id": 2}],
                    }
                ]
            },
        }
    )  # confidence out of range
    provider = FakeProvider([bad, _VALID_DIAGNOSE])
    result = run_loop(provider, _tools(), now="t")
    assert len(result.schema_violations) == 1
    assert result.diagnosis.abstained is False
    assert result.diagnosis.hypotheses[0].confidence == 0.9


def test_missing_type_is_a_violation_then_recovery():
    bad = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "hypotheses": [
                    {"cause": "c", "confidence": 0.5, "evidence": [{"id": 2}]}
                ]
            },
        }
    )  # evidence missing discriminator "type"
    provider = FakeProvider([bad, _VALID_DIAGNOSE])
    result = run_loop(provider, _tools(), now="t")
    assert len(result.schema_violations) == 1
    assert result.diagnosis.hypotheses[0].confidence == 0.9


def test_exhaustion_yields_abstention():
    provider = FakeProvider(["not json at all"] * 6)
    result = run_loop(provider, _tools(), now="t", max_steps=6)
    assert result.diagnosis.abstained is True
    assert result.diagnosis.abstention_reason
    assert len(result.schema_violations) == 6


def test_fabricated_id_measured_not_enforced():
    fab = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "s",
                "abstained": False,
                "hypotheses": [
                    {
                        "cause": "deploy a1b2c3d",
                        "confidence": 0.8,
                        "evidence": [
                            {"type": "log", "id": 999, "note": "does not exist"},
                            {"type": "commit", "sha": "a1b2c3d"},
                        ],
                    }
                ],
            },
        }
    )
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            fab,
        ]
    )
    result = run_loop(provider, _tools(), now="t")
    assert result.diagnosis.abstained is False
    assert ("log", 999) in result.cited_but_unseen_handles()
    assert ("commit", "a1b2c3d") not in result.cited_but_unseen_handles()


def test_model_abstention_passthrough():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "action": "diagnose",
                    "diagnosis": {
                        "abstained": True,
                        "abstention_reason": "signals too weak",
                        "hypotheses": [],
                    },
                }
            )
        ]
    )
    result = run_loop(provider, _tools(), now="t")
    assert result.diagnosis.abstained is True
    assert result.diagnosis.abstention_reason == "signals too weak"
