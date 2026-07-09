"""Tests for the ingestion normalisation primitives (v1.1, DR-0022)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quellgeist.ingest.normalize import (
    normalize_commits,
    normalize_level,
    normalize_log_rows,
    normalize_metric_series,
    normalize_ts,
)

_FIXTURES = Path(__file__).parents[1].parent / "evals" / "scenarios" / "fixtures"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-07-07T10:02:12Z", "2026-07-07T10:02:12Z"),  # canonical -> unchanged
        ("2026-07-07T10:02:12+00:00", "2026-07-07T10:02:12Z"),
        ("2026-07-07T15:32:12+05:30", "2026-07-07T10:02:12Z"),  # -> UTC
        ("2026-07-07T10:02:12.123456Z", "2026-07-07T10:02:12Z"),  # drop subseconds
        ("2026-07-07 10:02:12", "2026-07-07T10:02:12Z"),  # space, assumed UTC
        (1783418532, "2026-07-07T10:02:12Z"),  # epoch seconds
        (1783418532000, "2026-07-07T10:02:12Z"),  # epoch millis
        ("1783418532", "2026-07-07T10:02:12Z"),  # numeric string
    ],
)
def test_normalize_ts_forms(raw, expected):
    assert normalize_ts(raw) == expected


def test_normalize_ts_never_raises_on_garbage():
    assert normalize_ts("not a timestamp") == "not a timestamp"
    assert normalize_ts("") == ""
    assert normalize_ts(None) == ""  # tolerant, not a crash


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("error", "ERROR"),
        ("ERR", "ERROR"),
        ("Critical", "ERROR"),
        ("warn", "WARNING"),
        ("info", "INFO"),
        ("notice", "INFO"),
        ("debug", "DEBUG"),
        ("something", "SOMETHING"),
        (None, "INFO"),
    ],
)
def test_normalize_level(raw, expected):
    assert normalize_level(raw) == expected


def test_normalize_log_rows_aliases_and_coerces():
    raw = [
        {
            "timestamp": "2026-07-07T10:02:12+00:00",
            "severity": "error",
            "path": "/login",
            "status_code": "500",
            "message": "boom",
        }
    ]
    (row,) = normalize_log_rows(raw)
    assert row == {
        "id": 0,
        "ts": "2026-07-07T10:02:12Z",
        "level": "ERROR",
        "route": "/login",
        "status": 500,
        "msg": "boom",
    }


def test_normalize_log_rows_assigns_stable_ids_only_when_missing():
    raw = [
        {"id": 7, "message": "keeps its id"},
        {"message": "gets a fresh one after 7"},
    ]
    rows = normalize_log_rows(raw)
    assert [r["id"] for r in rows] == [7, 8]


def test_normalize_log_rows_omits_absent_http_fields():
    (row,) = normalize_log_rows([{"message": "a bare syslog-ish line"}])
    assert "route" not in row and "status" not in row
    assert row["level"] == "INFO"  # default when absent


def test_normalize_commits_aliases_and_drops_shaless():
    raw = [
        {"commit": "abc123", "subject": "fix", "date": "2026-07-07T10:00:00Z"},
        {"message": "no sha here"},  # dropped
    ]
    rows = normalize_commits(raw)
    assert rows == [
        {"sha": "abc123", "ts": "2026-07-07T10:00:00Z", "msg": "fix", "files": []}
    ]


def test_normalize_metric_series_normalizes_points_keeps_name():
    raw = [{"metric": "mem_rss", "points": [{"ts": 1783418532, "value": 5}]}]
    (series,) = normalize_metric_series(raw)
    assert series["metric"] == "mem_rss"
    assert series["points"] == [{"ts": "2026-07-07T10:02:12Z", "value": 5}]


# --- the frozen-invariant guard: canonical fixture data must be value-preserving.


def _iter_fixture_files():
    return sorted(_FIXTURES.glob("*.json"))


def test_canonical_fixture_rows_round_trip_unchanged():
    """DR-0022 promise: normalising an already-canonical row is a no-op on values,
    so hardening the real-file reader cannot drift the demo/eval behaviour. Every
    committed fixture's logs/commits/metrics must survive normalisation with
    identical values (ids preserved, timestamps unchanged, nothing dropped)."""
    checked = 0
    for path in _iter_fixture_files():
        scenario = json.loads(path.read_text(encoding="utf-8"))

        logs = scenario.get("logs", [])
        normed = normalize_log_rows(logs)
        assert [r["id"] for r in normed] == [r["id"] for r in logs], path.name
        for orig, out in zip(logs, normed, strict=True):
            assert out["ts"] == orig["ts"], path.name
            assert out["level"] == orig["level"], path.name
            assert out["msg"] == orig["msg"], path.name

        commits = scenario.get("commits", [])
        c_normed = normalize_commits(commits)
        assert [c["sha"] for c in c_normed] == [c["sha"] for c in commits], path.name

        metrics = scenario.get("metrics", [])
        if metrics:
            m_normed = normalize_metric_series(metrics)
            assert [m["metric"] for m in m_normed] == [
                m["metric"] for m in metrics
            ], path.name
        checked += 1
    assert checked > 50  # the whole committed suite, not an empty glob
