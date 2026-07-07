"""Quellgeist logs MCP server (Wave 1, Task 4).

A thin FastMCP wrapper that exposes the read-only ``query_logs`` tool over stdio.
The tool implementation and its (canonical, single-sourced) description live in
``quellgeist.servers.tools`` -- importing FastMCP is confined to this module, so
the CLI and eval harness pay no MCP-framework startup cost.

Log path: ``$QG_LOG_PATH`` if set, else ``demo/incident_logs.jsonl`` (run from the
repo root). The file is opened read-only. ``query_logs`` is re-exported for callers
that import it from here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from quellgeist.servers.tools import QUERY_LOGS_DESC, query_logs

__all__ = ["query_logs", "main", "mcp"]

mcp = FastMCP("quellgeist-logs")
mcp.tool(description=QUERY_LOGS_DESC)(query_logs)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
