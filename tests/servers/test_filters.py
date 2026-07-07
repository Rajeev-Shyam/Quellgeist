"""Tests for shared filter timestamp validation (Wave 2)."""

from __future__ import annotations

import pytest

from quellgeist.servers.filters import (
    filter_log_rows,
    filter_metric_rows,
    recent_commits,
)

ROWS = [{"id": 0, "ts": "2026-06-18T10:00:00Z", "level": "INFO", "route": "/x"}]
COMMITS = [{"sha": "a1b2c3d", "ts": "2026-06-18T10:00:00Z"}]
METRICS = [
    {
        "metric": "db_connections_in_use",
        "unit": "count",
        "points": [
            {"ts": "2026-06-18T09:59:00Z", "value": 5},
            {"ts": "2026-06-18T10:01:00Z", "value": 100},
        ],
    },
    {"metric": "memory_rss_bytes", "unit": "bytes", "points": []},
]


def test_canonical_since_is_accepted():
    assert filter_log_rows(ROWS, since="2026-06-18T09:00:00Z") == ROWS
    assert recent_commits(COMMITS, since="2026-06-18T09:00:00Z") == COMMITS


@pytest.mark.parametrize(
    "bad",
    [
        "yesterday",
        "2026-06-18",  # date only, no time
        "2026-6-18T10:00:00Z",  # not zero-padded -> breaks lexicographic order
        "2026-06-18T10:00:00",  # missing trailing Z
        "2026-06-18 10:00:00Z",  # space instead of T
    ],
)
def test_noncanonical_since_raises(bad):
    with pytest.raises(ValueError, match="since must be"):
        filter_log_rows(ROWS, since=bad)
    with pytest.raises(ValueError, match="since must be"):
        recent_commits(COMMITS, since=bad)
    with pytest.raises(ValueError, match="since must be"):
        filter_metric_rows(METRICS, since=bad)


def test_recent_commits_limit_keeps_n_most_recent():
    commits = [
        {"sha": "old", "ts": "2026-06-18T10:00:00Z"},
        {"sha": "new", "ts": "2026-06-18T11:00:00Z"},
    ]
    assert [c["sha"] for c in recent_commits(commits, limit=1)] == ["new"]
    assert recent_commits(commits, limit=0) == []


@pytest.mark.parametrize("bad", [-1, -2])
def test_recent_commits_negative_limit_raises(bad):
    # A negative limit would silently DROP the newest commit (list[:-1]); fail loud.
    with pytest.raises(ValueError, match="limit must be a non-negative"):
        recent_commits(COMMITS, limit=bad)


def test_metric_name_filter_selects_one_series():
    out = filter_metric_rows(METRICS, name="db_connections_in_use")
    assert [s["metric"] for s in out] == ["db_connections_in_use"]


def test_metric_since_trims_points_but_keeps_the_series_name():
    out = filter_metric_rows(
        METRICS, name="db_connections_in_use", since="2026-06-18T10:00:00Z"
    )
    (series,) = out
    assert series["metric"] == "db_connections_in_use"  # identity passes through
    assert [p["value"] for p in series["points"]] == [100]  # only the >= since point


def test_metric_no_filters_returns_all_series():
    assert {s["metric"] for s in filter_metric_rows(METRICS)} == {
        "db_connections_in_use",
        "memory_rss_bytes",
    }
