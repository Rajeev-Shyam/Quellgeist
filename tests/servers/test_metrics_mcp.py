"""Tests for the metrics MCP server (Wave 3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quellgeist.servers.metrics_mcp import query_metrics

SAMPLE_METRICS = [
    {
        "metric": "db_connections_in_use",
        "unit": "count",
        "points": [
            {"ts": "2026-06-23T12:09:00Z", "value": 5},
            {"ts": "2026-06-23T12:10:00Z", "value": 128},
        ],
    },
    {
        "metric": "memory_rss_bytes",
        "unit": "bytes",
        "points": [{"ts": "2026-06-23T12:10:00Z", "value": 900}],
    },
]


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_query_metrics_returns_all_series(tmp_path, monkeypatch):
    src = tmp_path / "metrics.json"
    _write_json(src, SAMPLE_METRICS)
    monkeypatch.setenv("QG_METRICS_PATH", str(src))

    result = query_metrics()

    assert {s["metric"] for s in result} == {
        "db_connections_in_use",
        "memory_rss_bytes",
    }


def test_name_selects_one_series_with_name_verbatim(tmp_path, monkeypatch):
    src = tmp_path / "metrics.json"
    _write_json(src, SAMPLE_METRICS)
    monkeypatch.setenv("QG_METRICS_PATH", str(src))

    result = query_metrics(name="db_connections_in_use")

    assert [s["metric"] for s in result] == ["db_connections_in_use"]
    assert [p["value"] for p in result[0]["points"]] == [5, 128]  # untrimmed


def test_since_trims_points(tmp_path, monkeypatch):
    src = tmp_path / "metrics.json"
    _write_json(src, SAMPLE_METRICS)
    monkeypatch.setenv("QG_METRICS_PATH", str(src))

    (series,) = query_metrics(
        name="db_connections_in_use", since="2026-06-23T12:09:30Z"
    )

    assert [p["value"] for p in series["points"]] == [128]  # only the >= since point


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_METRICS_PATH", str(tmp_path / "nope.json"))
    assert query_metrics() == []


def test_non_array_raises(tmp_path, monkeypatch):
    bad = tmp_path / "metrics.json"
    bad.write_text('{"metric": "x"}', encoding="utf-8")  # object, not array
    monkeypatch.setenv("QG_METRICS_PATH", str(bad))
    with pytest.raises(ValueError):
        query_metrics()
