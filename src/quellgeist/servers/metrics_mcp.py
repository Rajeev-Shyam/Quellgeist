"""Quellgeist metrics MCP server (Wave 3).

A thin FastMCP wrapper exposing the read-only ``query_metrics`` tool over stdio
(resource-exhaustion signals: memory / connection pools / queue depth). The
implementation and its (canonical, single-sourced) description live in
``quellgeist.servers.tools`` -- FastMCP is imported only here.

Source: ``$QG_METRICS_PATH`` if set, else ``demo/metrics.json`` (run from the repo
root). Opened read-only; returns ``[]`` if absent. ``query_metrics`` is re-exported
for callers that import it from here.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from quellgeist.servers.tools import QUERY_METRICS_DESC, query_metrics

__all__ = ["query_metrics", "main", "mcp"]

mcp = FastMCP("quellgeist-metrics")
mcp.tool(description=QUERY_METRICS_DESC)(query_metrics)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
