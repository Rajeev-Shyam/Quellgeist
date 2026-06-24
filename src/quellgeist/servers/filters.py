"""Shared read-only signal filters (Wave 1).

The logs and commits MCP servers and the eval harness all narrow the same
canned signals the same way -- logs by ``since``/``level``/``route``, commits
newest-first by ``since``/``limit``. That filtering is the load-bearing part of
DR-0009: ids and shas pass through VERBATIM, never renumbered by result
position, so an evidence handle resolves to the same row regardless of the
query. Centralising it in one public module means the servers and the eval
harness share a SINGLE implementation instead of reaching across modules into
each other's underscore-private helpers.
"""

from __future__ import annotations

from typing import Any


def filter_log_rows(
    rows: list[dict[str, Any]],
    since: str | None = None,
    level: str | None = None,
    route: str | None = None,
) -> list[dict[str, Any]]:
    """Apply optional, AND-combined filters. Returns rows unchanged, in source
    order, ids verbatim -- never renumbered by result position (DR-0009)."""
    level_norm = level.upper() if level else None
    out: list[dict[str, Any]] = []
    for row in rows:
        if since is not None and row.get("ts", "") < since:
            continue
        if level_norm is not None and row.get("level") != level_norm:
            continue
        if route is not None and row.get("route") != route:
            continue
        out.append(row)
    return out


def recent_commits(
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
