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
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from quellgeist.servers.filters import (
    filter_log_rows,
    filter_metric_rows,
    recent_commits,
)

DEFAULT_LOG_PATH = "demo/incident_logs.jsonl"
DEFAULT_DEPLOY_LOG = "demo/deploy_log.json"
DEFAULT_METRICS_PATH = "demo/metrics.json"

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


def _log_path() -> Path:
    return Path(os.environ.get("QG_LOG_PATH", DEFAULT_LOG_PATH))


def _read_log_rows(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL log into row dicts. Skips blank lines; lets malformed JSON
    raise -- surfacing real corruption rather than silently dropping a row whose
    id the fabrication check would then wrongly treat as nonexistent."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:  # read-only
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def query_logs(
    since: str | None = None,
    level: str | None = None,
    route: str | None = None,
) -> list[dict[str, Any]]:
    return filter_log_rows(_read_log_rows(_log_path()), since, level, route)


def _deploy_log_path() -> Path:
    return Path(os.environ.get("QG_DEPLOY_LOG", DEFAULT_DEPLOY_LOG))


def _read_commits(path: Path) -> list[dict[str, Any]]:
    """Read the deploy log (a JSON array of commit objects). Returns [] if the
    file is absent (no deploy injected yet). Malformed JSON / wrong top-level
    type raises -- surfacing real corruption rather than silently hiding a sha
    the fabrication check would then wrongly call fabricated."""
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
    a series the fabrication check would then wrongly call fabricated."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(
            f"{path}: expected a JSON array of metric series, got {type(data).__name__}"
        )
    return data


def query_metrics(
    name: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    return filter_metric_rows(_read_metrics(_metrics_path()), name, since)
