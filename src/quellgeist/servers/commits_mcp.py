"""Quellgeist commits MCP server (Wave 1, Task 5).

Exposes one read-only tool, ``get_recent_commits``, over stdio. It reads the
demo's deploy/commit history from ``demo/deploy_log.json`` (the plan's sanctioned
v1 source -- a local JSON array, no token, no network, reproducible in CI) and
returns commits newest-first, each carrying its ``sha`` VERBATIM. That sha is the
handle a ``CommitRef`` cites and the Wave 2 fabrication check looks up (DR-0009).

Source: ``$QG_DEPLOY_LOG`` if set, else ``demo/deploy_log.json`` resolved against
the CWD (run from the repo root). Opened read-only. Returns ``[]`` if the file is
absent (e.g. before a bad deploy is injected).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

DEFAULT_DEPLOY_LOG = "demo/deploy_log.json"

mcp = FastMCP("quellgeist-commits")


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


def _recent_commits(
    commits: list[dict[str, Any]],
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Newest-first, shas verbatim. Optional `since` keeps commits at or after
    that UTC ts (lexicographic compare is valid for the fixed
    %Y-%m-%dT%H:%M:%SZ format); optional `limit` keeps the N most recent."""
    selected = [c for c in commits if since is None or c.get("ts", "") >= since]
    selected.sort(key=lambda c: c.get("ts", ""), reverse=True)  # newest first
    if limit is not None:
        selected = selected[:limit]
    return selected


@mcp.tool(
    description=(
        "List the demo service's recent deploys/commits, newest first. Returns "
        "commit objects, each with a `sha` (cite this sha as evidence), `ts` (UTC, "
        "'YYYY-MM-DDTHH:MM:SSZ'), `msg`, and `files` (paths the commit touched). "
        "Optional `since` keeps commits at or after that UTC timestamp (same "
        "format); optional `limit` keeps only the N most recent. Use this to find "
        "what shipped just before an incident began. Read-only."
    )
)
def get_recent_commits(
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return _recent_commits(_read_commits(_deploy_log_path()), since, limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
