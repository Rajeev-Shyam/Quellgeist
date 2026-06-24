"""Tests for the quellgeist CLI (Wave 1, Task 8). Offline -- scripted fake provider."""

from __future__ import annotations

import json

import quellgeist.cli as cli
from quellgeist.agent.loop import ToolSpec

ERROR_ROWS = [
    {
        "id": 2,
        "ts": "2026-06-23T12:02:12Z",
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

_DIAGNOSE = json.dumps(
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
                        {"type": "commit", "sha": "a1b2c3d"},
                    ],
                }
            ],
            "suggested_actions": ["roll back a1b2c3d"],
        },
    }
)


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _wire(monkeypatch, scripted):
    monkeypatch.setattr(cli, "_make_provider", lambda model: FakeProvider(scripted))
    monkeypatch.setattr(
        cli,
        "_make_tools",
        lambda: [
            ToolSpec("query_logs", "logs", lambda **k: ERROR_ROWS),
            ToolSpec("get_recent_commits", "commits", lambda **k: COMMITS),
        ],
    )


def test_diagnose_prints_postmortem(monkeypatch, capsys):
    _wire(
        monkeypatch,
        [
            json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            _DIAGNOSE,
        ],
    )
    rc = cli.main(["diagnose"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "log #2" in out
    assert "commit a1b2c3d" in out
    assert "deploy a1b2c3d broke auth.verify_token" in out


def test_diagnose_writes_out_file(monkeypatch, capsys, tmp_path):
    _wire(monkeypatch, [_DIAGNOSE])
    out_file = tmp_path / "pm.md"
    rc = cli.main(["diagnose", "--out", str(out_file)])
    assert rc == 0
    assert out_file.exists()
    assert "log #2" in out_file.read_text(encoding="utf-8")


def test_show_trace_goes_to_stderr(monkeypatch, capsys):
    _wire(monkeypatch, [_DIAGNOSE])
    rc = cli.main(["diagnose", "--show-trace"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "[trace]" in err


def test_provider_failure_exits_nonzero(monkeypatch, capsys):
    class Boom:
        def complete(self, messages):
            raise RuntimeError("provider down")

    monkeypatch.setattr(cli, "_make_provider", lambda model: Boom())
    monkeypatch.setattr(
        cli, "_make_tools", lambda: [ToolSpec("query_logs", "l", lambda **k: [])]
    )
    rc = cli.main(["diagnose"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "diagnosis failed" in err
