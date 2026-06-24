"""Tests for the logs MCP server (Wave 1, Task 4)."""

from __future__ import annotations

import json
from pathlib import Path

from quellgeist.servers.filters import filter_log_rows
from quellgeist.servers.logs_mcp import query_logs

# Mirrors the live JSONL shape and bad_deploy_0001.json. The ERROR rows are ids
# 2,3,4 -- deliberately NOT 0..n -- so a renumber-by-index bug is caught.
SAMPLE_ROWS = [
    {
        "id": 0,
        "ts": "2026-06-18T09:55:01Z",
        "level": "INFO",
        "route": "/login",
        "status": 200,
        "msg": "login ok",
    },
    {
        "id": 1,
        "ts": "2026-06-18T10:01:30Z",
        "level": "INFO",
        "route": "/login",
        "status": 200,
        "msg": "login ok",
    },
    {
        "id": 2,
        "ts": "2026-06-18T10:02:12Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "TypeError: 'NoneType' object is not subscriptable in auth.verify_token",
    },
    {
        "id": 3,
        "ts": "2026-06-18T10:03:05Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "TypeError: 'NoneType' object is not subscriptable in auth.verify_token",
    },
    {
        "id": 4,
        "ts": "2026-06-18T10:07:44Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "TypeError: 'NoneType' object is not subscriptable in auth.verify_token",
    },
    {
        "id": 5,
        "ts": "2026-06-18T10:08:10Z",
        "level": "INFO",
        "route": "/data",
        "status": 200,
        "msg": "data served",
    },
]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_query_logs_filters_by_level(tmp_path, monkeypatch):
    log = tmp_path / "incident_logs.jsonl"
    _write_jsonl(log, SAMPLE_ROWS)
    monkeypatch.setenv("QG_LOG_PATH", str(log))

    result = query_logs(level="ERROR")

    assert [r["level"] for r in result] == ["ERROR", "ERROR", "ERROR"]
    # load-bearing: original source ids survive (2,3,4), NOT renumbered 0,1,2
    assert [r["id"] for r in result] == [2, 3, 4]


def test_level_filter_is_case_insensitive(tmp_path, monkeypatch):
    log = tmp_path / "incident_logs.jsonl"
    _write_jsonl(log, SAMPLE_ROWS)
    monkeypatch.setenv("QG_LOG_PATH", str(log))
    assert [r["id"] for r in query_logs(level="error")] == [2, 3, 4]


def test_filter_preserves_source_ids_in_memory():
    result = filter_log_rows(SAMPLE_ROWS, route="/login", level="ERROR")
    assert [r["id"] for r in result] == [2, 3, 4]


def test_route_filter():
    assert [r["id"] for r in filter_log_rows(SAMPLE_ROWS, route="/data")] == [5]


def test_since_filter_keeps_at_or_after():
    result = filter_log_rows(SAMPLE_ROWS, since="2026-06-18T10:07:44Z")
    assert [r["id"] for r in result] == [4, 5]


def test_no_filters_returns_all_in_source_order():
    assert [r["id"] for r in filter_log_rows(SAMPLE_ROWS)] == [0, 1, 2, 3, 4, 5]


def test_missing_log_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_LOG_PATH", str(tmp_path / "nope.jsonl"))
    assert query_logs() == []


def test_blank_lines_skipped(tmp_path, monkeypatch):
    log = tmp_path / "incident_logs.jsonl"
    log.write_text(json.dumps(SAMPLE_ROWS[2]) + "\n\n  \n", encoding="utf-8")
    monkeypatch.setenv("QG_LOG_PATH", str(log))
    assert [r["id"] for r in query_logs()] == [2]
