"""Tests for `quellgeist ingest` (v1.1, DR-0022)."""

from __future__ import annotations

import json

import quellgeist.cli as cli


def test_ingest_writes_canonical_files(tmp_path, capsys):
    logs = tmp_path / "app.log"
    logs.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-07-07T10:00:00Z","severity":"info","path":"/health","status_code":200,"message":"ok"}',
                "2026-07-07T10:00:01Z ERROR NoneType in verify_token",
            ]
        ),
        encoding="utf-8",
    )
    us = "\x1f"
    deploys = tmp_path / "gitlog.txt"
    deploys.write_text(
        f"a1b2c3d{us}2026-07-07T09:59:00Z{us}deploy: refactor auth\ndemo/app/auth.py\n",
        encoding="utf-8",
    )
    metrics = tmp_path / "prom.json"
    metrics.write_text(
        json.dumps(
            {
                "data": {
                    "result": [
                        {
                            "metric": {"__name__": "mem_rss"},
                            "values": [[1783418400, "900"]],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "signals"

    rc = cli.main(
        [
            "ingest",
            "--logs",
            str(logs),
            "--deploys",
            str(deploys),
            "--metrics",
            str(metrics),
            "--out-dir",
            str(out),
        ]
    )
    assert rc == 0

    log_rows = [
        json.loads(line)
        for line in (out / "incident_logs.jsonl").read_text().splitlines()
    ]
    assert [r["level"] for r in log_rows] == ["INFO", "ERROR"]
    assert [r["id"] for r in log_rows] == [0, 1]

    commits = json.loads((out / "deploy_log.json").read_text())
    assert commits[0]["sha"] == "a1b2c3d" and commits[0]["files"] == [
        "demo/app/auth.py"
    ]

    series = json.loads((out / "metrics.json").read_text())
    assert series[0]["metric"] == "mem_rss"

    # copy-pasteable next-steps land on stdout
    stdout = capsys.readouterr().out
    assert "export QG_LOG_PATH=" in stdout
    assert "quellgeist diagnose" in stdout


def test_ingest_requires_a_source(capsys):
    rc = cli.main(["ingest", "--out-dir", "x"])
    assert rc == 2
    assert "at least one of" in capsys.readouterr().err


def test_ingested_files_are_consumable_by_the_tools(tmp_path, monkeypatch):
    """End-to-end contract: what `ingest` writes is exactly what the tools read."""
    logs = tmp_path / "raw.jsonl"
    logs.write_text(
        '{"time":"2026-07-07T10:00:00Z","level":"error","url":"/login","message":"boom"}\n',
        encoding="utf-8",
    )
    out = tmp_path / "signals"
    assert cli.main(["ingest", "--logs", str(logs), "--out-dir", str(out)]) == 0

    from quellgeist.servers import tools

    monkeypatch.setenv("QG_LOG_PATH", str(out / "incident_logs.jsonl"))
    rows = tools.query_logs(level="ERROR")
    assert [r["msg"] for r in rows] == ["boom"]
    assert rows[0]["route"] == "/login"
