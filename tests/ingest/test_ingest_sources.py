"""Tests for the tolerant real-source readers (v1.1, DR-0022)."""

from __future__ import annotations

import json

from quellgeist.ingest.sources import (
    from_git_log_text,
    read_deploy_source,
    read_log_source,
    read_metrics_source,
)


def test_read_log_jsonl_preserves_ids(tmp_path):
    p = tmp_path / "logs.jsonl"
    p.write_text(
        '{"id":2,"ts":"2026-07-07T10:02:12Z","level":"ERROR","route":"/login","status":500,"msg":"boom"}\n',
        encoding="utf-8",
    )
    res = read_log_source(p)
    assert res.skipped == 0 and res.coerced == 0
    assert [r["id"] for r in res.rows] == [2]  # existing id preserved


def test_read_log_mixed_and_malformed_never_crashes(tmp_path):
    p = tmp_path / "app.log"
    p.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-07-07T10:00:00Z","severity":"error","message":"json line"}',
                "2026-07-07T10:00:01Z ERROR a plain-text stack-trace line",
                "totally unstructured line",
                "",  # blank -> skipped, not coerced
            ]
        ),
        encoding="utf-8",
    )
    res = read_log_source(p)
    assert len(res.rows) == 3  # blank dropped, the rest kept
    assert res.coerced == 2  # the two non-JSON lines
    # the plain-text line lifted its leading ts + level
    text_row = res.rows[1]
    assert text_row["ts"] == "2026-07-07T10:00:01Z"
    assert text_row["level"] == "ERROR"
    assert "stack-trace" in text_row["msg"]


def test_read_log_json_array(tmp_path):
    p = tmp_path / "export.json"
    p.write_text(
        json.dumps(
            [
                {"time": "2026-07-07T10:00:00Z", "level": "info", "msg": "a"},
                {"time": "2026-07-07T10:00:01Z", "level": "error", "msg": "b"},
            ]
        ),
        encoding="utf-8",
    )
    res = read_log_source(p)
    assert [r["level"] for r in res.rows] == ["INFO", "ERROR"]
    assert [r["id"] for r in res.rows] == [0, 1]  # assigned in order


def test_read_log_directory_merges_and_reassigns_ids(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    # two files, each with its own id=0 -> would collide if preserved
    (d / "a.jsonl").write_text(
        '{"id":0,"ts":"2026-07-07T10:00:02Z","level":"INFO","msg":"second in time"}\n',
        encoding="utf-8",
    )
    (d / "b.jsonl").write_text(
        '{"id":0,"ts":"2026-07-07T10:00:01Z","level":"ERROR","msg":"first in time"}\n',
        encoding="utf-8",
    )
    res = read_log_source(d)
    assert res.files == 2
    # sorted by ts, ids reassigned uniquely 0..n
    assert [r["id"] for r in res.rows] == [0, 1]
    assert [r["msg"] for r in res.rows] == ["first in time", "second in time"]


def test_read_log_missing_path_is_empty(tmp_path):
    res = read_log_source(tmp_path / "nope.log")
    assert res.rows == [] and res.files == 0


def test_from_git_log_text():
    us = "\x1f"
    text = (
        f"a1b2c3d{us}2026-07-07T10:01:50+00:00{us}deploy: refactor token parsing\n"
        "demo/app/auth.py\n"
        "\n"
        f"9f8e7d6{us}2026-07-06T16:20:00+00:00{us}docs: update README\n"
        "README.md\n"
    )
    commits = from_git_log_text(text)
    assert [c["sha"] for c in commits] == ["a1b2c3d", "9f8e7d6"]
    assert commits[0]["files"] == ["demo/app/auth.py"]
    assert commits[0]["msg"] == "deploy: refactor token parsing"


def test_read_deploy_source_git_log_text(tmp_path):
    us = "\x1f"
    p = tmp_path / "gitlog.txt"
    p.write_text(
        f"a1b2c3d{us}2026-07-07T10:01:50Z{us}fix\nsrc/x.py\n", encoding="utf-8"
    )
    res = read_deploy_source(p)
    assert res.rows[0]["sha"] == "a1b2c3d"
    assert res.rows[0]["ts"] == "2026-07-07T10:01:50Z"


def test_read_deploy_source_github_payload(tmp_path):
    p = tmp_path / "commits.json"
    p.write_text(
        json.dumps(
            [
                {
                    "sha": "deadbeef",
                    "commit": {
                        "message": "chore: bump",
                        "author": {"date": "2026-07-07T09:00:00Z"},
                    },
                    "files": [{"filename": "pyproject.toml"}],
                }
            ]
        ),
        encoding="utf-8",
    )
    res = read_deploy_source(p)
    assert res.rows == [
        {
            "sha": "deadbeef",
            "ts": "2026-07-07T09:00:00Z",
            "msg": "chore: bump",
            "files": ["pyproject.toml"],
        }
    ]


def test_read_metrics_prometheus_range(tmp_path):
    p = tmp_path / "prom.json"
    p.write_text(
        json.dumps(
            {
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"__name__": "mem_rss_bytes", "job": "web"},
                            "values": [[1783418400, "900"], [1783418460, "1800"]],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    res = read_metrics_source(p)
    assert [s["metric"] for s in res.rows] == ["mem_rss_bytes"]
    pts = res.rows[0]["points"]
    assert pts[0]["ts"] == "2026-07-07T10:00:00Z" and pts[0]["value"] == 900.0


def test_read_metrics_canonical_array_passthrough(tmp_path):
    p = tmp_path / "metrics.json"
    canonical = [
        {
            "metric": "q",
            "unit": "count",
            "points": [{"ts": "2026-07-07T10:00:00Z", "value": 4}],
        }
    ]
    p.write_text(json.dumps(canonical), encoding="utf-8")
    res = read_metrics_source(p)
    assert res.rows == canonical
