"""End-to-end 'real use' harness (v1.1, DR-0022).

The deterministic proof that the ingestion + robustness layer works on *real-shaped*
data, using the same scripted-provider technique the rest of the suite uses (no
model, CI-safe). It builds a realistic messy incident -- a ~950-line log mixing
foreign JSON field names, plain-text stack traces, and a malformed line; a
``git log`` deploy source; and a Prometheus metrics response -- runs it through
``quellgeist ingest`` and then the REAL ``run_loop`` + the live citation check, and
asserts the four production properties the review flagged as missing:

  1. it does not crash on malformed/mixed real data;
  2. the observation is bounded (a huge log can't blow the context window);
  3. the loop produces the correct evidence-cited diagnosis; and
  4. every citation resolves to a real signal (zero fabrication) at real-use time.
"""

from __future__ import annotations

import json

import quellgeist.cli as cli
from quellgeist.agent.citations import check_fabrication
from quellgeist.agent.loop import run_loop
from quellgeist.servers import tools

_US = "\x1f"


class FakeProvider:
    """A competent reasoner, scripted: query errors -> list deploys -> diagnose."""

    def __init__(self, scripted):
        self.scripted = list(scripted)

    def complete(self, messages):
        return self.scripted.pop(0)


def _write_messy_incident(tmp_path):
    """~950 lines of realistic mess with a bad-deploy incident at the tail."""
    lines: list[str] = []
    # 900 lines of benign noise, alternating foreign-JSON and plain-text shapes.
    for i in range(900):
        ts = f"2026-07-07T10:{i // 60:02d}:{i % 60:02d}Z"
        if i % 2 == 0:
            lines.append(
                json.dumps(
                    {
                        "timestamp": ts,
                        "severity": "info",
                        "path": "/data",
                        "status_code": 200,
                        "message": "ok",
                    }
                )
            )
        else:
            lines.append(f"{ts} INFO served /health 200")
    lines.append("!! a corrupt half-written line {not json")  # malformed -> coerced
    # the incident: verify_token 500s, foreign field names + a plain stack line
    for j in range(5):
        ts = f"2026-07-07T10:15:{j:02d}Z"
        lines.append(
            json.dumps(
                {
                    "timestamp": ts,
                    "severity": "error",
                    "url": "/login",
                    "status_code": 500,
                    "message": "TypeError: NoneType in auth.verify_token",
                }
            )
        )
    log = tmp_path / "app.log"
    log.write_text("\n".join(lines), encoding="utf-8")
    return log


def _write_deploys(tmp_path):
    text = (
        f"c0ffee1{_US}2026-07-07T09:30:00Z{_US}chore: bump deps\nrequirements.txt\n"
        "\n"
        f"badf00d{_US}2026-07-07T10:14:55Z{_US}deploy: refactor token parsing\n"
        "demo/app/auth.py\n"
    )
    p = tmp_path / "gitlog.txt"
    p.write_text(text, encoding="utf-8")
    return p


def _write_metrics(tmp_path):
    p = tmp_path / "prom.json"
    p.write_text(
        json.dumps(
            {
                "data": {
                    "result": [
                        {
                            "metric": {"__name__": "http_5xx_total"},
                            "values": [[1783419300, "0"], [1783419305, "5"]],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return p


def test_real_incident_end_to_end(tmp_path, monkeypatch, capsys):
    log = _write_messy_incident(tmp_path)
    deploys = _write_deploys(tmp_path)
    metrics = _write_metrics(tmp_path)
    out = tmp_path / "signals"

    # 1. ingest the real sources into the canonical files (must not crash)
    assert (
        cli.main(
            [
                "ingest",
                "--logs",
                str(log),
                "--deploys",
                str(deploys),
                "--metrics",
                str(metrics),
                "--out-dir",
                str(out),
            ]
        )
        == 0
    )

    monkeypatch.setenv("QG_LOG_PATH", str(out / "incident_logs.jsonl"))
    monkeypatch.setenv("QG_DEPLOY_LOG", str(out / "deploy_log.json"))
    monkeypatch.setenv("QG_METRICS_PATH", str(out / "metrics.json"))
    monkeypatch.setenv("QG_MAX_ROWS", "200")

    # discover the real handles a reasoner would cite (the incident error + culprit)
    all_rows = tools.all_log_rows()
    error_id = next(
        r["id"]
        for r in all_rows
        if "verify_token" in r["msg"] and r["level"] == "ERROR"
    )
    culprit_sha = "badf00d"

    # 2. the observation is bounded even though the raw log is large
    assert len(all_rows) > 200  # the raw incident really is big
    assert len(tools.query_logs()) == 200  # capped for the model
    error_obs = tools.query_logs(level="ERROR")
    assert error_id in [r["id"] for r in error_obs]  # the culprit survives the cap

    # 3. run the REAL loop with a scripted reasoner over the real tools
    diagnosis_msg = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "bad deploy badf00d broke /login",
                "abstained": False,
                "hypotheses": [
                    {
                        "cause": "deploy badf00d refactored auth.py -> NoneType in verify_token; /login 500s",
                        "confidence": 0.95,
                        "evidence": [
                            {
                                "type": "log",
                                "id": error_id,
                                "note": "first verify_token 500",
                            },
                            {
                                "type": "commit",
                                "sha": culprit_sha,
                                "note": "the refactor deploy",
                            },
                        ],
                    }
                ],
                "suggested_actions": ["roll back badf00d"],
            },
        }
    )
    provider = FakeProvider(
        [
            json.dumps({"action": "query_logs", "args": {"level": "ERROR"}}),
            json.dumps({"action": "get_recent_commits", "args": {}}),
            diagnosis_msg,
        ]
    )
    result = run_loop(
        provider, cli._make_tools(), now="2026-07-07T10:15:10Z", max_steps=8
    )

    assert not result.diagnosis.abstained
    assert result.diagnosis.hypotheses[0].evidence[0].id == error_id

    # 4. every cited handle resolves to a real signal -- zero fabrication at use time
    fab = check_fabrication(
        result.diagnosis,
        tools.all_log_rows(),
        tools.get_recent_commits(),
        tools.query_metrics(),
    )
    assert fab.ok, fab.fabricated


def test_real_incident_through_cli_diagnose(tmp_path, monkeypatch, capsys):
    """The same real incident, driven the way a user would: `quellgeist diagnose`
    with a (scripted) reasoner -> a cited postmortem + a clean citation check."""
    log = _write_messy_incident(tmp_path)
    deploys = _write_deploys(tmp_path)
    out = tmp_path / "signals"
    assert (
        cli.main(
            [
                "ingest",
                "--logs",
                str(log),
                "--deploys",
                str(deploys),
                "--out-dir",
                str(out),
            ]
        )
        == 0
    )

    monkeypatch.setenv("QG_LOG_PATH", str(out / "incident_logs.jsonl"))
    monkeypatch.setenv("QG_DEPLOY_LOG", str(out / "deploy_log.json"))
    monkeypatch.setenv("QG_METRICS_PATH", str(tmp_path / "none.json"))

    error_id = next(r["id"] for r in tools.all_log_rows() if "verify_token" in r["msg"])
    diagnosis_msg = json.dumps(
        {
            "action": "diagnose",
            "diagnosis": {
                "summary": "bad deploy badf00d broke /login",
                "abstained": False,
                "hypotheses": [
                    {
                        "cause": "deploy badf00d broke verify_token",
                        "confidence": 0.95,
                        "evidence": [
                            {"type": "log", "id": error_id},
                            {"type": "commit", "sha": "badf00d"},
                        ],
                    }
                ],
                "suggested_actions": ["roll back badf00d"],
            },
        }
    )
    monkeypatch.setattr(cli, "_make_provider", lambda m: FakeProvider([diagnosis_msg]))
    rc = cli.main(["diagnose", "--show-trace", "--strict-citations"])
    captured = capsys.readouterr()
    assert rc == 0
    assert f"log #{error_id}" in captured.out
    assert "commit badf00d" in captured.out
    assert "citations=ok" in captured.err
