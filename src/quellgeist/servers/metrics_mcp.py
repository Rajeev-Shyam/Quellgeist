"""Quellgeist metrics MCP server (Wave 3).

Exposes one read-only tool, ``query_metrics``, over stdio. It reads the demo's
metric series from ``demo/metrics.json`` (a local JSON array -- no network,
reproducible in CI) and returns matching series, each carrying its ``metric``
name VERBATIM: the handle a ``MetricRef`` cites and the fabrication check looks up
(DR-0009). Resource-exhaustion incidents (memory / connection-pool / queue depth)
live here -- a series that climbs to a ceiling is the tell a diagnosis must cite
alongside the culprit deploy.

Source: ``$QG_METRICS_PATH`` if set, else ``demo/metrics.json`` resolved against
the CWD (run from the repo root). Opened read-only. Returns ``[]`` if the file is
absent (e.g. before a resource incident is injected).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from quellgeist.servers.filters import filter_metric_rows

DEFAULT_METRICS_PATH = "demo/metrics.json"

mcp = FastMCP("quellgeist-metrics")


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


@mcp.tool(
    description=(
        "Query the demo service's metric time-series. Returns series objects, each "
        "with a `metric` name (cite this name as evidence), `unit`, and `points` "
        "(each with a `ts` UTC 'YYYY-MM-DDTHH:MM:SSZ' and a `value`). Optional "
        "`name` selects one series; optional `since` keeps points at or after that "
        "UTC timestamp. Use this for resource-exhaustion signals -- memory, "
        "connection pools, queue depth -- that logs alone don't show. Read-only."
    )
)
def query_metrics(
    name: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    return filter_metric_rows(_read_metrics(_metrics_path()), name, since)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
