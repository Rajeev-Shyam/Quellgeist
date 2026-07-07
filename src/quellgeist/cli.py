"""Quellgeist CLI (Wave 1, Task 8).

`quellgeist diagnose` runs the whole Wave 1 spine on the configured demo signals:
build the model-agnostic provider -> gather evidence via the JSON-action loop ->
render a templated postmortem. stdout carries ONLY the postmortem (a clean,
pipeable artifact); stderr carries diagnostics. Provider failures (model down,
quota, missing key) degrade to a one-line error + exit 1 -- never a traceback.
Abstention ("insufficient evidence") is a valid outcome and exits 0.

``_make_provider`` / ``_make_tools`` are deliberately small seams so the command
is unit-tested end-to-end with a scripted fake provider and no network.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from quellgeist.agent.loop import ToolSpec, run_loop
from quellgeist.agent.providers import LiteLLMProvider, Provider
from quellgeist.output.postmortem import render_postmortem, write_postmortem
from quellgeist.servers.commits_mcp import get_recent_commits
from quellgeist.servers.logs_mcp import query_logs
from quellgeist.servers.metrics_mcp import query_metrics

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _make_provider(model: str | None) -> Provider:
    return LiteLLMProvider(model=model)


def _make_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            "query_logs",
            "Query structured incident logs; optional since/level/route filters; "
            "returns rows each with a stable integer id.",
            query_logs,
        ),
        ToolSpec(
            "get_recent_commits",
            "List recent deploys newest-first; optional since/limit; returns "
            "commits with sha, ts, msg, files.",
            get_recent_commits,
        ),
        ToolSpec(
            "query_metrics",
            "Query metric time-series (memory/connections/queue depth) for "
            "resource incidents; optional name/since; each series carries a "
            "`metric` name (cite it), `unit`, and `points`.",
            query_metrics,
        ),
    ]


def _diagnose(args: argparse.Namespace) -> int:
    provider = _make_provider(args.model)
    tools = _make_tools()
    now = datetime.now(UTC).strftime(_TS_FMT)
    try:
        result = run_loop(provider, tools, now=now, max_steps=args.max_steps)
    except (
        Exception
    ) as e:  # provider down / quota / missing key -> clean exit, no traceback
        print(f"error: diagnosis failed: {e}", file=sys.stderr)
        return 1

    print(render_postmortem(result.diagnosis, title=args.title))

    if args.out:
        write_postmortem(result.diagnosis, args.out, title=args.title, fmt=args.format)
        print(f"wrote postmortem to {args.out}", file=sys.stderr)
    if args.show_trace:
        print(
            f"[trace] steps={result.steps} "
            f"tool_calls={[name for name, _ in result.tool_calls]} "
            f"schema_violations={len(result.schema_violations)} "
            f"cited_but_unseen={result.cited_but_unseen_handles() or '∅'}",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="quellgeist",
        description="Incident-triage agent: diagnose a production incident.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser(
        "diagnose", help="diagnose the current incident from logs + recent deploys"
    )
    d.add_argument(
        "--out",
        help="also write the postmortem to this file (e.g. postmortem.md or .html)",
    )
    d.add_argument(
        "--format",
        choices=["md", "html"],
        default=None,
        help="format for --out (default: infer from the extension, else markdown)",
    )
    d.add_argument(
        "--model",
        help="override the reasoner (LiteLLM model string); default $QG_MODEL",
    )
    d.add_argument(
        "--max-steps", type=int, default=8, help="max agent loop steps (default: 8)"
    )
    d.add_argument("--title", default="Incident Postmortem", help="postmortem title")
    d.add_argument(
        "--show-trace",
        action="store_true",
        help="print loop trace + citation fidelity to stderr",
    )
    d.set_defaults(func=_diagnose)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
