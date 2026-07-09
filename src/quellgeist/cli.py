"""Quellgeist CLI (Wave 1, Task 8; ingestion + live citation check added v1.1).

`quellgeist diagnose` runs the whole spine on the configured signals: build the
model-agnostic provider -> gather evidence via the JSON-action loop -> render a
templated postmortem. stdout carries ONLY the postmortem (a clean, pipeable
artifact); stderr carries diagnostics. Provider failures (model down, quota,
missing key) degrade to a one-line error + exit 1 -- never a traceback. Abstention
("insufficient evidence") is a valid outcome and exits 0.

`quellgeist ingest` is the adapter layer (DR-0022): it reads REAL log / deploy /
metric sources (mixed-format logs, ``git log`` text or a GitHub payload, a
Prometheus response) and writes the three canonical files the tools read, so an
operator can point Quellgeist at their own incident instead of hand-authoring the
schema.

After a live diagnosis the CLI runs the deterministic, keyless citation check
against the FULL real signal set (the project's headline guarantee, previously
only enforced in the eval harness): a cited handle absent from the real signals is
flagged, and ``--strict-citations`` turns that into a non-zero exit for CI.

``_make_provider`` / ``_make_tools`` are deliberately small seams so the command
is unit-tested end-to-end with a scripted fake provider and no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from quellgeist.agent.citations import check_fabrication, real_signal_handles
from quellgeist.agent.loop import ToolSpec, run_loop
from quellgeist.agent.providers import (
    LiteLLMProvider,
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.agent.schema import Diagnosis
from quellgeist.demo_incident import demo_diagnosis
from quellgeist.ingest.sources import (
    read_deploy_source,
    read_log_source,
    read_metrics_source,
)
from quellgeist.output.postmortem import render_postmortem, write_postmortem
from quellgeist.servers.tools import (
    GET_RECENT_COMMITS_DESC,
    QUERY_LOGS_DESC,
    QUERY_METRICS_DESC,
    all_log_rows,
    get_recent_commits,
    query_logs,
    query_metrics,
)

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
_DEFAULT_TITLE = "Incident Postmortem"

# Exit code for a live diagnosis whose citations failed the deterministic check
# under --strict-citations (distinct from 1 = provider failure, 2 = usage error).
_EXIT_FABRICATION = 3


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


def _verify_citations(diagnosis: Diagnosis) -> frozenset[tuple[str, object]] | None:
    """Deterministic, keyless citation check against the FULL (uncapped) real
    signal set the tools are configured to read. Returns the set of fabricated
    handles (empty = clean), or ``None`` when there are no real signals to check
    against (e.g. an embedded/scripted run) -- unverifiable, so it is not reported
    as a failure. Any read error degrades to ``None`` rather than crashing a run."""
    if diagnosis.abstained:
        return frozenset()
    try:
        logs = all_log_rows()
        commits = get_recent_commits()
        metrics = query_metrics()
    except Exception:
        return None
    if not real_signal_handles(logs, commits, metrics):
        return None  # nothing loaded to check against -> unverifiable, skip
    return check_fabrication(diagnosis, logs, commits, metrics).fabricated


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
    if rc != 0:
        return rc

    fabricated = _verify_citations(result.diagnosis)
    if args.show_trace:
        if fabricated is None:
            citations = "unverified"
        elif fabricated:
            citations = (
                "FABRICATED{"
                + ",".join(f"{t}:{k}" for t, k in sorted(fabricated))
                + "}"
            )
        else:
            citations = "ok"
        print(
            f"[trace] steps={result.steps} "
            f"tool_calls={[name for name, _ in result.tool_calls]} "
            f"schema_violations={len(result.schema_violations)} "
            f"cited_but_unseen={result.cited_but_unseen_handles() or '∅'} "
            f"citations={citations}",
            file=sys.stderr,
        )
    if fabricated:
        joined = ", ".join(f"{t}:{k}" for t, k in sorted(fabricated))
        print(
            f"warning: diagnosis cited evidence absent from the real signals: "
            f"{joined}. This is the failure mode Quellgeist guards against — treat "
            f"the diagnosis with suspicion.",
            file=sys.stderr,
        )
        if args.strict_citations:
            return _EXIT_FABRICATION
    return 0


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _ingest(args: argparse.Namespace) -> int:
    """Read real log/deploy/metric sources into the three canonical files."""
    if not (args.logs or args.deploys or args.metrics):
        print(
            "error: give at least one of --logs / --deploys / --metrics "
            "(see 'quellgeist ingest --help').",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"error: could not create --out-dir {out_dir}: {e}", file=sys.stderr)
        return 1

    written: list[tuple[str, Path]] = []
    try:
        if args.logs:
            res = read_log_source(args.logs)
            path = out_dir / "incident_logs.jsonl"
            _write_jsonl(path, res.rows)
            print(
                f"logs:    {len(res.rows)} rows from {res.files} file(s) -> {path}"
                + (
                    f"  ({res.coerced} coerced, {res.skipped} skipped)"
                    if res.coerced or res.skipped
                    else ""
                ),
                file=sys.stderr,
            )
            written.append(("QG_LOG_PATH", path))

        if args.deploys:
            res = read_deploy_source(args.deploys)
            path = out_dir / "deploy_log.json"
            path.write_text(json.dumps(res.rows, indent=2) + "\n", encoding="utf-8")
            print(f"deploys: {len(res.rows)} commits -> {path}", file=sys.stderr)
            written.append(("QG_DEPLOY_LOG", path))

        if args.metrics:
            res = read_metrics_source(args.metrics)
            path = out_dir / "metrics.json"
            path.write_text(json.dumps(res.rows, indent=2) + "\n", encoding="utf-8")
            print(f"metrics: {len(res.rows)} series -> {path}", file=sys.stderr)
            written.append(("QG_METRICS_PATH", path))
    except OSError as e:
        print(f"error: ingest failed: {e}", file=sys.stderr)
        return 1

    # Print copy-pasteable next steps: point the env at the canonical files, then
    # diagnose. Goes to stdout so it can be `eval`'d or captured.
    print("# Quellgeist ingest complete. Next:")
    for var, path in written:
        print(f"export {var}={path}")
    print("quellgeist diagnose --show-trace   # add --model / a provider key")
    return 0


def _build_parser() -> argparse.ArgumentParser:
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
    d.add_argument(
        "--strict-citations",
        action="store_true",
        help="exit non-zero if the diagnosis cites evidence absent from the real "
        "signals (for CI gating; the check runs and warns regardless)",
    )
    d.set_defaults(func=_diagnose)

    ing = sub.add_parser(
        "ingest",
        help="normalise real log/deploy/metric sources into the canonical files",
        description="Read real-world sources into the three canonical files the "
        "tools read, so you can point Quellgeist at your own incident.",
    )
    ing.add_argument(
        "--logs",
        help="a log file or a directory of them (JSONL, JSON array, or plain text)",
    )
    ing.add_argument(
        "--deploys",
        help="deploys as a JSON array / GitHub payload, or `git log` text "
        "(git log --no-color --pretty=format:%%H%%x1f%%cI%%x1f%%s --name-only)",
    )
    ing.add_argument(
        "--metrics",
        help="metrics as a Prometheus range/instant response or a canonical JSON array",
    )
    ing.add_argument(
        "--out-dir",
        default="quellgeist-signals",
        help="directory to write the canonical files into (default: quellgeist-signals)",
    )
    ing.set_defaults(func=_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
