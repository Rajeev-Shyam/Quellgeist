"""Real-file robustness of the log tool path (v1.1, DR-0022).

These exercise the CLI/MCP real-file path (``servers.tools``), NOT the frozen eval
path (``run_evals.scenario_tools`` -> ``filters`` on in-memory fixtures), which is
deliberately left byte-identical.
"""

from __future__ import annotations

import json

from quellgeist.servers import tools


def test_query_logs_does_not_crash_on_malformed_lines(tmp_path, monkeypatch):
    p = tmp_path / "logs.jsonl"
    p.write_text(
        "\n".join(
            [
                '{"id":1,"ts":"2026-07-07T10:00:00Z","level":"ERROR","route":"/login","status":500,"msg":"boom"}',
                "a plain text line, not JSON at all",
                '{"id":2,"ts":"2026-07-07T10:00:01Z","level":"ERROR","route":"/login","status":500,"msg":"boom2"}',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QG_LOG_PATH", str(p))
    rows = tools.query_logs(level="ERROR")  # used to raise JSONDecodeError
    assert [r["id"] for r in rows] == [1, 2]


def test_query_logs_normalizes_aliased_fields(tmp_path, monkeypatch):
    p = tmp_path / "logs.jsonl"
    p.write_text(
        '{"timestamp":"2026-07-07T15:32:12+05:30","severity":"error","path":"/login","status_code":"500","message":"boom"}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("QG_LOG_PATH", str(p))
    (row,) = tools.query_logs()
    assert row["ts"] == "2026-07-07T10:02:12Z"  # offset -> UTC
    assert row["level"] == "ERROR" and row["route"] == "/login" and row["status"] == 500


def test_query_logs_caps_observation(tmp_path, monkeypatch):
    p = tmp_path / "big.jsonl"
    p.write_text(
        "".join(
            json.dumps(
                {"id": i, "ts": "2026-07-07T10:00:00Z", "level": "INFO", "msg": "x"}
            )
            + "\n"
            for i in range(1000)
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QG_LOG_PATH", str(p))
    monkeypatch.setenv("QG_MAX_ROWS", "50")
    rows = tools.query_logs()
    assert len(rows) == 50
    assert [r["id"] for r in rows] == list(range(950, 1000))  # most-recent kept


def test_all_log_rows_is_uncapped(tmp_path, monkeypatch):
    p = tmp_path / "big.jsonl"
    p.write_text(
        "".join(
            json.dumps(
                {"id": i, "ts": "2026-07-07T10:00:00Z", "level": "INFO", "msg": "x"}
            )
            + "\n"
            for i in range(300)
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QG_LOG_PATH", str(p))
    monkeypatch.setenv("QG_MAX_ROWS", "50")
    assert len(tools.query_logs()) == 50  # capped for the observation
    assert len(tools.all_log_rows()) == 300  # uncapped for the citation check


def test_query_logs_demo_shape_unchanged(tmp_path, monkeypatch):
    """A canonical demo-shaped log is returned unchanged (values), so the live
    demo path is not disturbed by the hardening."""
    rows_in = [
        {
            "id": 0,
            "ts": "2026-07-07T10:00:00Z",
            "level": "INFO",
            "route": "/health",
            "status": 200,
            "msg": "ok",
        },
        {
            "id": 1,
            "ts": "2026-07-07T10:00:01Z",
            "level": "ERROR",
            "route": "/login",
            "status": 500,
            "msg": "boom",
        },
    ]
    p = tmp_path / "incident_logs.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows_in), encoding="utf-8")
    monkeypatch.setenv("QG_LOG_PATH", str(p))
    assert tools.query_logs() == rows_in


def test_query_metrics_caps_points_keeps_name(tmp_path, monkeypatch):
    series = [
        {
            "metric": "worker_queue_depth",
            "unit": "count",
            "points": [
                {"ts": f"2026-07-07T10:{i:02d}:00Z", "value": i} for i in range(60)
            ],
        }
    ]
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps(series), encoding="utf-8")
    monkeypatch.setenv("QG_METRICS_PATH", str(p))
    monkeypatch.setenv("QG_MAX_POINTS", "10")
    (out,) = tools.query_metrics()
    assert out["metric"] == "worker_queue_depth"  # cited handle preserved
    assert len(out["points"]) == 10  # points capped
