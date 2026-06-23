"""Tests for the commits MCP server (Wave 1, Task 5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quellgeist.servers.commits_mcp import _recent_commits, get_recent_commits

# Mirrors demo/deploy_log.json written by demo/chaos/bad_deploy.py: stored
# oldest-first (benign README commit, then the bad auth.py deploy ~30s ago).
SAMPLE_COMMITS = [
    {
        "sha": "9f8e7d6",
        "ts": "2026-06-22T16:20:00Z",
        "msg": "docs: update README",
        "files": ["README.md"],
    },
    {
        "sha": "a1b2c3d",
        "ts": "2026-06-23T12:09:52Z",
        "msg": "deploy: refactor token parsing",
        "files": ["demo/app/auth.py"],
    },
]


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_get_recent_commits_newest_first(tmp_path, monkeypatch):
    log = tmp_path / "deploy_log.json"
    _write_json(log, SAMPLE_COMMITS)
    monkeypatch.setenv("QG_DEPLOY_LOG", str(log))

    result = get_recent_commits()

    # newest-first: the bad deploy leads, sha verbatim, files passed through
    assert [c["sha"] for c in result] == ["a1b2c3d", "9f8e7d6"]
    assert result[0]["files"] == ["demo/app/auth.py"]


def test_limit_keeps_n_most_recent():
    assert [c["sha"] for c in _recent_commits(SAMPLE_COMMITS, limit=1)] == ["a1b2c3d"]


def test_since_keeps_at_or_after():
    result = _recent_commits(SAMPLE_COMMITS, since="2026-06-23T00:00:00Z")
    assert [c["sha"] for c in result] == ["a1b2c3d"]


def test_sha_preserved_verbatim():
    assert "a1b2c3d" in [c["sha"] for c in _recent_commits(SAMPLE_COMMITS)]


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("QG_DEPLOY_LOG", str(tmp_path / "nope.json"))
    assert get_recent_commits() == []


def test_non_array_raises(tmp_path, monkeypatch):
    bad = tmp_path / "deploy_log.json"
    bad.write_text('{"sha": "x"}', encoding="utf-8")  # object, not array
    monkeypatch.setenv("QG_DEPLOY_LOG", str(bad))
    with pytest.raises(ValueError):
        get_recent_commits()
