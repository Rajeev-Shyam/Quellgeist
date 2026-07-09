"""Incident-scoped tool closures (Wave 7, T7.4; DR-0023 concurrency isolation).

**Why this exists (the design decision the plan flagged).** The frozen
``servers/tools.py`` reads the signal paths from *process-global* ``os.environ``
(`QG_LOG_PATH` etc.). A concurrent service cannot use that: two incidents running in
parallel worker threads would clobber each other's env and cross-read signals. So the
worker never mutates global env — it builds ``ToolSpec`` closures bound to *this
incident's* snapshot directory, reusing the exact same reading/filtering/normalisation
(`ingest` + `servers.filters`) and the **same frozen tool-description strings** imported
from ``servers.tools``. Nothing frozen is touched; concurrency is correct by construction.

The per-observation caps (``QG_MAX_ROWS`` / ``QG_MAX_POINTS``) match the CLI's behaviour
but warn via structured logs, not stderr. The fabrication check reads the FULL, uncapped
snapshot via ``read_signals``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quellgeist.agent.loop import ToolSpec
from quellgeist.ingest.sources import read_log_source
from quellgeist.servers.filters import (
    filter_log_rows,
    filter_metric_rows,
    recent_commits,
)
from quellgeist.servers.tools import (
    DEFAULT_MAX_POINTS,
    DEFAULT_MAX_ROWS,
    GET_RECENT_COMMITS_DESC,
    QUERY_LOGS_DESC,
    QUERY_METRICS_DESC,
)

# Canonical snapshot filenames (the service's snapshot writer uses the same names).
SNAPSHOT_LOG = "incident_logs.jsonl"
SNAPSHOT_DEPLOY = "deploy_log.json"
SNAPSHOT_METRICS = "metrics.json"


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val >= 0 else default


def _read_log_rows(snapshot_dir: Path) -> list[dict[str, Any]]:
    """Uncapped canonical log rows from the snapshot (tolerant read via ingest)."""
    return read_log_source(snapshot_dir / SNAPSHOT_LOG).rows


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    """Strict read of a canonical JSON-array file (deploys/metrics). Returns [] if
    absent; raises on a wrong top-level type (surface real corruption, DR-0009) —
    matching ``servers.tools`` behaviour for these small canonical files."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array, got {type(data).__name__}")
    return data


def read_signals(
    snapshot_dir: str | Path,
) -> tuple[list[dict], list[dict], list[dict]]:
    """The FULL (uncapped) signal set for this incident — for the deterministic
    citation check, which must validate against every real handle, not the capped
    observation."""
    d = Path(snapshot_dir)
    return (
        _read_log_rows(d),
        _read_json_array(d / SNAPSHOT_DEPLOY),
        _read_json_array(d / SNAPSHOT_METRICS),
    )


def incident_tools(snapshot_dir: str | Path) -> list[ToolSpec]:
    """Build the three read-only tools bound to ``snapshot_dir`` — concurrency-safe
    (no global env), reusing the frozen descriptions + filters/ingest."""
    d = Path(snapshot_dir)
    max_rows = _int_env("QG_MAX_ROWS", DEFAULT_MAX_ROWS)
    max_points = _int_env("QG_MAX_POINTS", DEFAULT_MAX_POINTS)

    def query_logs(since=None, level=None, route=None):
        rows = filter_log_rows(_read_log_rows(d), since, level, route)
        if max_rows and len(rows) > max_rows:
            rows = rows[-max_rows:]  # most-recent tail (active incident's errors)
        return rows

    def get_recent_commits(since=None, limit=None):
        return recent_commits(_read_json_array(d / SNAPSHOT_DEPLOY), since, limit)

    def query_metrics(name=None, since=None):
        series = filter_metric_rows(_read_json_array(d / SNAPSHOT_METRICS), name, since)
        if not max_points:
            return series
        out = []
        for s in series:
            pts = s.get("points", [])
            out.append(
                {**s, "points": pts[-max_points:]} if len(pts) > max_points else s
            )
        return out

    return [
        ToolSpec("query_logs", QUERY_LOGS_DESC, query_logs),
        ToolSpec("get_recent_commits", GET_RECENT_COMMITS_DESC, get_recent_commits),
        ToolSpec("query_metrics", QUERY_METRICS_DESC, query_metrics),
    ]
