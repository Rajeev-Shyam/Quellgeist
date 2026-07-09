"""Read-only tool implementations + the canonical tool contract (Wave 5).

The three evidence tools are consumed from THREE surfaces that must agree: the CLI
(in-process), the eval harness (over canned scenario data), and the published MCP
servers (over stdio). This module is the single source for (a) the file-backed tool
functions and (b) the tool *descriptions*, so those surfaces cannot drift.

Two deliberate properties:

- **No FastMCP import here.** Only the ``*_mcp`` servers import FastMCP; the CLI and
  the eval harness import this module and pay no MCP-framework startup cost.
- **The descriptions are the exact strings the DR-0020 fine-tune was trained and
  measured on** (via ``evals.run_evals.scenario_tools``). Production (the CLI) now
  serves that same text, eliminating a train/serve prompt skew for a
  prompt-sensitive reasoner.

Paths are resolved from operator-set env vars (``QG_LOG_PATH`` / ``QG_DEPLOY_LOG`` /
``QG_METRICS_PATH``) with repo-relative defaults; files are opened read-only. Ids /
shas / metric names pass through VERBATIM (never renumbered by result position) --
the load-bearing DR-0009 property, enforced in ``filters``.

**Real-data robustness (v1.1, DR-0022).** The log reader tolerates real files
(mixed JSON / plain text; a malformed line is coerced, never fatal) and normalises
them into the canonical schema via ``ingest``, and ``query_logs`` caps how many rows
one call returns so a large production log cannot produce a context-blowing
observation. This is confined to the CLI/MCP *real-file* path: the eval harness
serves in-memory fixtures through ``filters`` directly, so the frozen measurement
path is untouched. The commits/metrics readers stay strict (small, canonical files;
feed messy sources through ``quellgeist ingest`` first).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from quellgeist.ingest.sources import read_log_source
from quellgeist.servers.filters import (
    filter_log_rows,
    filter_metric_rows,
    recent_commits,
)

DEFAULT_LOG_PATH = "demo/incident_logs.jsonl"
DEFAULT_DEPLOY_LOG = "demo/deploy_log.json"
DEFAULT_METRICS_PATH = "demo/metrics.json"

# Real-data guardrails (v1.1). Defaults are far above any demo/fixture result, so
# the demo and the frozen eval path are byte-identical; they only bite real,
# large production signals.
DEFAULT_MAX_ROWS = 200
DEFAULT_MAX_POINTS = 1000

# Canonical tool descriptions -- the single source shared by the CLI, the eval
# harness (scenario_tools), and the MCP servers. These are byte-identical to the
# text the DR-0020 fine-tune was trained + measured on; do not reword without
# retraining (it would reintroduce train/serve skew).
QUERY_LOGS_DESC = "Query structured incident logs; optional since/level/route; rows carry a stable int id."
GET_RECENT_COMMITS_DESC = "List recent deploys newest-first; optional since/limit; commits carry sha/ts/msg/files."
QUERY_METRICS_DESC = (
    "Query metric time-series (memory/connections/queue depth) for resource "
    "incidents; optional name/since; each series carries a `metric` name "
    "(cite it), `unit`, and `points`."
)

# Warn at most once per (message) so a tool re-read inside the loop doesn't spam
# stderr; cleared implicitly by process lifetime (the loop is one process).
_warned: set[str] = set()


def _warn_once(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        print(f"warning: {msg}", file=sys.stderr)


def _int_env(name: str, default: int) -> int:
    """Read a non-negative int env override; fall back to ``default`` on anything
    unparseable so a stray value can never crash a diagnosis."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return val if val >= 0 else default


def _log_path() -> Path:
    return Path(os.environ.get("QG_LOG_PATH", DEFAULT_LOG_PATH))


def _read_log_rows(path: Path) -> list[dict[str, Any]]:
    """Read a log file (or directory) into canonical rows, tolerantly (v1.1).

    Real logs mix formats and contain the odd malformed line; those are coerced or
    skipped and counted, never fatal (a single bad line used to crash the whole
    tool call). Field names are normalised and source-stable ids assigned via
    ``ingest``. An already-canonical demo/exported log is unchanged."""
    result = read_log_source(path)
    if result.coerced or result.skipped:
        _warn_once(
            f"{path}: normalised real log data "
            f"({result.coerced} non-JSON line(s) coerced, "
            f"{result.skipped} entr(y/ies) skipped)"
        )
    return result.rows


def _cap_rows(rows: list[dict[str, Any]], tool: str) -> list[dict[str, Any]]:
    """Bound a log observation to the most-recent ``QG_MAX_ROWS`` rows so a large
    production log cannot produce a context-blowing single turn. Keeps the tail
    (most recent, where an active incident's errors are) in source order and warns
    the operator to narrow with filters."""
    cap = _int_env("QG_MAX_ROWS", DEFAULT_MAX_ROWS)
    if cap and len(rows) > cap:
        _warn_once(
            f"{tool} returned {len(rows)} rows; showing the most-recent {cap} "
            f"(raise QG_MAX_ROWS, or narrow with since/level/route)"
        )
        return rows[-cap:]
    return rows


def query_logs(
    since: str | None = None,
    level: str | None = None,
    route: str | None = None,
) -> list[dict[str, Any]]:
    rows = filter_log_rows(_read_log_rows(_log_path()), since, level, route)
    return _cap_rows(rows, "query_logs")


def all_log_rows() -> list[dict[str, Any]]:
    """Every canonical log row, UNCAPPED -- for the deterministic citation check,
    which must validate cited handles against the true full signal set, not the
    display-capped observation ``query_logs`` returns."""
    return _read_log_rows(_log_path())


def _deploy_log_path() -> Path:
    return Path(os.environ.get("QG_DEPLOY_LOG", DEFAULT_DEPLOY_LOG))


def _read_commits(path: Path) -> list[dict[str, Any]]:
    """Read the deploy log (a JSON array of commit objects). Returns [] if the
    file is absent (no deploy injected yet). Malformed JSON / wrong top-level
    type raises -- surfacing real corruption rather than silently hiding a sha
    the fabrication check would then wrongly call fabricated. Feed messy sources
    (git log, GitHub payloads) through ``quellgeist ingest`` to get this shape."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a JSON array of commits, got {type(data).__name__}"
        )
    return data


def get_recent_commits(
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return recent_commits(_read_commits(_deploy_log_path()), since, limit)


def _metrics_path() -> Path:
    return Path(os.environ.get("QG_METRICS_PATH", DEFAULT_METRICS_PATH))


def _read_metrics(path: Path) -> list[dict[str, Any]]:
    """Read the metrics source (a JSON array of series objects). Returns [] if the
    file is absent (no resource incident injected yet). Malformed JSON / wrong
    top-level type raises -- surfacing real corruption rather than silently hiding
    a series the fabrication check would then wrongly call fabricated. Feed a
    Prometheus response through ``quellgeist ingest`` to get this shape."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a JSON array of metric series, got {type(data).__name__}"
        )
    return data


def _cap_points(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound each series' point list to the most-recent ``QG_MAX_POINTS`` so a
    long time-series can't blow up an observation. The series NAME (the cited
    handle) is always preserved, so the citation check is unaffected."""
    cap = _int_env("QG_MAX_POINTS", DEFAULT_MAX_POINTS)
    if not cap:
        return series
    out: list[dict[str, Any]] = []
    for s in series:
        points = s.get("points", [])
        if len(points) > cap:
            _warn_once(
                f"query_metrics: series {s.get('metric')!r} has {len(points)} "
                f"points; showing the most-recent {cap} (raise QG_MAX_POINTS)"
            )
            s = {**s, "points": points[-cap:]}
        out.append(s)
    return out


def query_metrics(
    name: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    return _cap_points(filter_metric_rows(_read_metrics(_metrics_path()), name, since))
