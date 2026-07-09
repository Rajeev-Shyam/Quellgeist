"""Live citation guarantee in `quellgeist diagnose` (v1.1, DR-0022).

The deterministic, keyless fabrication check now runs at real-use time, not only
in the eval harness: a diagnosis that cites a handle absent from the real signals
is flagged, and ``--strict-citations`` makes it a non-zero exit for CI.
"""

from __future__ import annotations

import json

import quellgeist.cli as cli


class FakeProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _diagnose_citing(log_id):
    return json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "s",
                "abstained": False,
                "hypotheses": [
                    {
                        "cause": "c",
                        "confidence": 0.9,
                        "evidence": [{"type": "log", "id": log_id}],
                    }
                ],
                "suggested_actions": ["x"],
            },
        }
    )


def _wire_real_signals(monkeypatch, tmp_path):
    """Real single-row log; absent deploy/metrics files -> a non-empty, checkable
    signal set so the citation check actually runs (not the unverifiable skip)."""
    log = tmp_path / "incident_logs.jsonl"
    log.write_text(
        '{"id":1,"ts":"2026-07-07T10:00:00Z","level":"ERROR","route":"/login","status":500,"msg":"boom"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("QG_LOG_PATH", str(log))
    monkeypatch.setenv("QG_DEPLOY_LOG", str(tmp_path / "none.json"))
    monkeypatch.setenv("QG_METRICS_PATH", str(tmp_path / "none.json"))


def test_fabricated_citation_is_warned(monkeypatch, capsys, tmp_path):
    _wire_real_signals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli, "_make_provider", lambda m: FakeProvider([_diagnose_citing(999)])
    )
    rc = cli.main(["diagnose"])
    err = capsys.readouterr().err
    assert rc == 0  # warns by default, does not fail
    assert "cited evidence absent from the real signals" in err
    assert "log:999" in err


def test_strict_citations_exits_nonzero_on_fabrication(monkeypatch, capsys, tmp_path):
    _wire_real_signals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli, "_make_provider", lambda m: FakeProvider([_diagnose_citing(999)])
    )
    rc = cli.main(["diagnose", "--strict-citations"])
    assert rc == 3  # _EXIT_FABRICATION


def test_valid_citation_passes_clean(monkeypatch, capsys, tmp_path):
    _wire_real_signals(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli, "_make_provider", lambda m: FakeProvider([_diagnose_citing(1)])
    )
    rc = cli.main(["diagnose", "--show-trace", "--strict-citations"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "citations=ok" in err
    assert "cited evidence absent" not in err


def test_unverifiable_when_no_real_signals(monkeypatch, capsys, tmp_path):
    """No real signal files -> the check can't run, so it is reported as
    'unverified', never a false fabrication alarm."""
    monkeypatch.setenv("QG_LOG_PATH", str(tmp_path / "none.jsonl"))
    monkeypatch.setenv("QG_DEPLOY_LOG", str(tmp_path / "none.json"))
    monkeypatch.setenv("QG_METRICS_PATH", str(tmp_path / "none.json"))
    monkeypatch.setattr(
        cli, "_make_provider", lambda m: FakeProvider([_diagnose_citing(1)])
    )
    rc = cli.main(["diagnose", "--show-trace", "--strict-citations"])
    err = capsys.readouterr().err
    assert rc == 0
    assert "citations=unverified" in err
