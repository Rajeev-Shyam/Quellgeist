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


def test_make_tools_wires_all_three_servers():
    """Regression: the CLI must expose the same tool surface as the eval harness
    -- query_metrics was missing, so `quellgeist diagnose` could not diagnose a
    resource-exhaustion incident even though the eval path could."""
    assert [t.name for t in cli._make_tools()] == [
        "query_logs",
        "get_recent_commits",
        "query_metrics",
    ]


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


def test_diagnose_writes_html_out_file(monkeypatch, capsys, tmp_path):
    _wire(monkeypatch, [_DIAGNOSE])
    out_file = tmp_path / "pm.html"  # extension -> HTML
    rc = cli.main(["diagnose", "--out", str(out_file)])
    assert rc == 0
    body = out_file.read_text(encoding="utf-8")
    assert body.startswith("<!doctype html>")
    assert "log #2" in body
    # stdout stays markdown regardless of the file format
    assert "log #2" in capsys.readouterr().out


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


def test_demo_is_keyless_and_never_calls_a_provider(monkeypatch, capsys):
    # If --demo touched the model, this provider factory would blow up.
    def _boom(model):
        raise AssertionError("--demo must not build a provider")

    monkeypatch.setattr(cli, "_make_provider", _boom)
    rc = cli.main(["diagnose", "--demo"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "rendered from gold" in out  # labelled, not passed off as live output
    assert "log #2" in out and "commit a1b2c3d" in out


def test_demo_writes_html_keyless(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        cli, "_make_provider", lambda m: (_ for _ in ()).throw(AssertionError())
    )
    out_file = tmp_path / "demo.html"
    rc = cli.main(["diagnose", "--demo", "--out", str(out_file)])
    assert rc == 0
    assert out_file.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "a1b2c3d" in out_file.read_text(encoding="utf-8")


def test_format_without_out_is_rejected(capsys):
    rc = cli.main(
        ["diagnose", "--format", "html"]
    )  # no --out -> silent no-op otherwise
    err = capsys.readouterr().err
    assert rc == 2
    assert "--format applies to --out" in err


def test_out_write_failure_is_clean_not_a_traceback(monkeypatch, capsys, tmp_path):
    _wire(monkeypatch, [_DIAGNOSE])
    # a directory path is unwritable as a file -> OSError inside write_postmortem
    rc = cli.main(["diagnose", "--out", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "could not write --out" in err
    assert "Traceback" not in err


def test_keyless_run_is_clean_and_hints(tmp_path):
    """A real keyless run (default gemini, no key) must exit 1 with a one-line
    error + hint and NO litellm traceback/log-noise (the 'never a traceback'
    contract). Runs in a subprocess to exercise the real litellm path."""
    import os
    import subprocess
    import sys

    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")
    }
    env["QG_MODEL"] = "gemini/gemini-3.5-flash"  # force the no-key gemini path
    proc = subprocess.run(
        [sys.executable, "-m", "quellgeist.cli", "diagnose"],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 1, combined
    assert "Traceback" not in combined, combined
    assert "error: diagnosis failed" in combined
    assert "hint:" in combined
    assert "GEMINI_API_KEY" in combined  # points at the actual fix
