"""Quellgeist commits MCP server (Wave 1, Task 5).

A thin FastMCP wrapper exposing the read-only ``get_recent_commits`` tool over
stdio. The implementation and its (canonical, single-sourced) description live in
``quellgeist.servers.tools`` -- FastMCP is imported only here.

Source: ``$QG_DEPLOY_LOG`` if set, else ``demo/deploy_log.json`` (run from the repo
root). Opened read-only; returns ``[]`` if absent. ``get_recent_commits`` is
re-exported for callers that import it from here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from quellgeist.servers.tools import GET_RECENT_COMMITS_DESC, get_recent_commits

__all__ = ["get_recent_commits", "main", "mcp"]

mcp = FastMCP("quellgeist-commits")
mcp.tool(description=GET_RECENT_COMMITS_DESC)(get_recent_commits)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
