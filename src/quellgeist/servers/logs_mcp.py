"""Quellgeist logs MCP server (Wave 1, Task 4).

Exposes one read-only tool, ``query_logs``, over stdio. It reads the demo
service's structured JSONL incident log and returns matching rows, each carrying
its producer-assigned, source-stable ``id`` VERBATIM -- never renumbered by the
filtered-result position. That id is what a ``LogRef`` cites and what the Wave 2
deterministic fabrication check looks up (DR-0009), so renumbering here would
silently corrupt the reliability guarantee.

Log path: ``$QG_LOG_PATH`` if set, else ``demo/incident_logs.jsonl`` resolved
against the current working directory (run the server from the repo root). The
file is opened read-only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from quellgeist.servers.filters import filter_log_rows

DEFAULT_LOG_PATH = "demo/incident_logs.jsonl"

mcp = FastMCP("quellgeist-logs")


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


@mcp.tool(
    description=(
        "Query the demo service's structured incident logs. Returns matching log "
        "rows as JSON objects, each with a stable integer `id` (cite this id as "
        "evidence), plus `ts` (UTC, 'YYYY-MM-DDTHH:MM:SSZ'), `level`, `route`, "
        "`status`, and `msg`. All filters are optional and AND-combined: `since` "
        "keeps rows at or after that UTC timestamp (same format); `level` keeps "
        "rows of that severity (e.g. 'ERROR'); `route` keeps rows for that path "
        "(e.g. '/login'). Omit a filter to match all. Read-only."
    )
)
def query_logs(
    since: str | None = None,
    level: str | None = None,
    route: str | None = None,
) -> list[dict[str, Any]]:
    return filter_log_rows(_read_log_rows(_log_path()), since, level, route)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
