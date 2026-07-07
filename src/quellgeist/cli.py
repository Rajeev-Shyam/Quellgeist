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
from quellgeist.agent.providers import (
    LiteLLMProvider,
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.demo_incident import demo_diagnosis
from quellgeist.output.postmortem import render_postmortem, write_postmortem
from quellgeist.servers.tools import (
    GET_RECENT_COMMITS_DESC,
    QUERY_LOGS_DESC,
    QUERY_METRICS_DESC,
    get_recent_commits,
    query_logs,
    query_metrics,
)

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DEFAULT_TITLE = "Incident Postmortem"


def _make_provider(model: str | None) -> Provider:
    return LiteLLMProvider(model=model)


def _make_tools() -> list[ToolSpec]:
    # Descriptions come from the single canonical source (servers.tools) -- the
    # exact text the eval harness and the fine-tune use, so the CLI's in-process
    # run matches what was measured (no train/serve prompt skew).
    return [
        ToolSpec("query_logs", QUERY_LOGS_DESC, query_logs),
        ToolSpec("get_recent_commits", GET_RECENT_COMMITS_DESC, get_recent_commits),
        ToolSpec("query_metrics", QUERY_METRICS_DESC, query_metrics),
    ]


def _clean_error(exc: BaseException) -> str:
    """One clean line: litellm embeds a full ``traceback.format_exc()`` into some
    exception *messages* (e.g. APIConnectionError), so ``str(exc)`` alone would
    print a traceback. Drop everything from the embedded trace onward."""
    msg = str(exc)
    idx = msg.find("\nTraceback")
    return msg[:idx].rstrip() if idx != -1 else msg


def _error_hint(exc: BaseException) -> str:
    """A short, actionable second line for the common failure modes, so a keyless
    first run points the user at the fix instead of a bare provider error."""
    if is_auth_error(exc):
        return (
            "invalid model credentials — check your provider key (e.g. "
            "GEMINI_API_KEY), or run a local model with --model ollama_chat/... "
            "(see the README 'Running the model')."
        )
    if is_provider_unavailable(exc):
        # litellm reports a *missing* key as an APIConnectionError too, so cover
        # both the no-key first-run and a genuine transient outage.
        return (
            "could not reach the model — set a valid key (e.g. GEMINI_API_KEY) or "
            "run a local model with --model ollama_chat/..., or retry if this is a "
            "transient outage (see the README 'Running the model')."
        )
    return ""


def _emit(diagnosis, args: argparse.Namespace, title: str) -> int:
    """Render the postmortem to stdout and, if --out, to a file. Shared by the
    live and --demo paths so the two can't drift."""
    print(render_postmortem(diagnosis, title=title))
    if args.out:
        try:
            write_postmortem(diagnosis, args.out, title=title, fmt=args.format)
        except OSError as e:  # unwritable path -> clean error, not a traceback
            print(f"error: could not write --out {args.out}: {e}", file=sys.stderr)
            return 1
        print(f"wrote postmortem to {args.out}", file=sys.stderr)
    return 0


def _diagnose(args: argparse.Namespace) -> int:
    if args.format and not args.out:
        # stdout is always Markdown (a clean, pipeable artifact); --format only
        # governs the --out file, so --format without --out is a silent no-op.
        print(
            "error: --format applies to --out; stdout is always Markdown. "
            "Pass --out FILE (e.g. --out postmortem.html).",
            file=sys.stderr,
        )
        return 2

    if args.demo:
        # Keyless: render the demo incident's gold diagnosis, no model needed --
        # so a clean clone shows a real-shaped postmortem on the first run.
        title = args.title
        if title == _DEFAULT_TITLE:
            title = "Incident Postmortem (demo — rendered from gold)"
        return _emit(demo_diagnosis(), args, title)

    provider = _make_provider(args.model)
    tools = _make_tools()
    now = datetime.now(UTC).strftime(_TS_FMT)
    try:
        result = run_loop(provider, tools, now=now, max_steps=args.max_steps)
    except (
        Exception
    ) as e:  # provider down / quota / missing key -> clean exit, no traceback
        print(f"error: diagnosis failed: {_clean_error(e)}", file=sys.stderr)
        hint = _error_hint(e)
        if hint:
            print(f"hint: {hint}", file=sys.stderr)
        return 1

    rc = _emit(result.diagnosis, args, args.title)
    if rc == 0 and args.show_trace:
        print(
            f"[trace] steps={result.steps} "
            f"tool_calls={[name for name, _ in result.tool_calls]} "
            f"schema_violations={len(result.schema_violations)} "
            f"cited_but_unseen={result.cited_but_unseen_handles() or '∅'}",
            file=sys.stderr,
        )
    return rc


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
        "--demo",
        action="store_true",
        help="render the demo incident's gold diagnosis with NO model or key "
        "(keyless; a real-shaped postmortem on a clean clone)",
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
    d.add_argument("--title", default=_DEFAULT_TITLE, help="postmortem title")
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
