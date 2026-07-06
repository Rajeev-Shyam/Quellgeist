"""Run ONE comparison-matrix cell (Wave 4, Task 4).

A cell = (reasoner from ``QG_MODEL``) x (verifier on/off) x (scenario set),
run for ``--passes`` scored passes (default 3 -- temp-0 local decoding is not
run-to-run deterministic, DR-0019) with real cost instrumentation and the
DR-0020 decision-8 trace audits. Every rider that DR pre-registered is
enforced or recorded here:

- **The verifier is pinned or the cell refuses to run.** With ``--verify``,
  ``QG_VERIFIER_MODEL`` must be set explicitly and must differ from the
  reasoner model -- the ``QG_MODEL`` fallback (and an equal pin) would let the
  tuned model verify itself, changing two variables in one cell. A deliberate
  self-verification ablation is possible only via ``--allow-self-verify``.
- **Cost is measured, not estimated:** per-scenario reasoner/verifier call
  counts, prompt/completion tokens (from the backend's usage report, when it
  gives one), call latency, observation sizes, and wall time.
- **Trace audits run alongside the scores** (``evals/matrix/audits.py``).
  The bank-token and train-timestamp audits engage automatically on holdout
  cells (every scenario id ``hold_``-prefixed); on other sets they would
  false-positive on legitimately grounded vocabulary.
- **Fixtures-distribution scenarios carry a ``core_overlap`` flag** so the
  report splits core-overlapping from core-fresh results (the post-tune
  fixtures number is same-bank recombination, never "generalisation").

Scoring: ``--score gate`` (default) is the deterministic judge + fabrication
bar (``EvalResult.passed``); ``--score abstain`` is the abstention probe's
rule -- a scenario passes iff the model DELIBERATELY abstained (loop-fallback
and verifier-forced abstentions do not count) with zero fabrication.

Outputs under ``--out`` (default ``runs/matrix/<cell-id>/``, gitignored):
``pass_<k>.jsonl`` (one record per scenario, written incrementally) and
``cell.json`` (config echo + per-pass and aggregate summaries; written only
when the cell COMPLETES, so a half-run can never be read as a measurement).

Exit codes: 0 = cell completed (a 0/16 pass rate is data, not an error);
2 = configuration error; 3 = backend unavailable/unauthenticated (skipped).

    QG_MODEL="ollama_chat/quellgeist-qwen3-dr0020" \\
    QG_VERIFIER_MODEL="ollama_chat/qwen3:4b-instruct-2507-q4_K_M" \\
    python -m evals.matrix.run_cell --cell-id tuned+verifier--holdout \\
        --scenarios evals/scenarios/holdout --verify
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.matrix.audits import (
    core_overlaps_train,
    fixtures_bank_argument_leaks,
    train_timestamp_argument_leaks,
    unobserved_argument_values,
)
from evals.run_evals import EvalResult, run_scenario
from evals.scenarios.generator import Scenario, load_scenario
from quellgeist.agent.loop import FALLBACK_ABSTENTION_PREFIXES
from quellgeist.agent.providers import (
    DEFAULT_MODEL,
    LiteLLMProvider,
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.agent.verifier import default_verifier_provider

_OBS_PREFIX = "Observation from "


def _git_head() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _usage_delta(provider: Provider | None, start: int) -> tuple[dict | None, int]:
    """Per-scenario slice of a provider's ``CallUsage`` log. ``None`` token
    sums mean the backend did not report usage for at least one call in the
    slice -- a partial sum would understate cost, so it is not quoted."""
    calls = getattr(provider, "calls", None)
    if calls is None:
        return None, start
    new = calls[start:]

    def _sum(attr: str) -> int | None:
        vals = [getattr(c, attr) for c in new]
        if not vals or any(v is None for v in vals):
            return None
        return sum(vals)

    return {
        "calls": len(new),
        "prompt_tokens": _sum("prompt_tokens"),
        "completion_tokens": _sum("completion_tokens"),
        "latency_s": round(sum(c.latency_s for c in new), 3),
    }, len(calls)


def _deliberate_abstention(r: EvalResult) -> bool:
    """The abstention probe's rule (DR-0020 decision 6): the LOOP-level
    diagnosis abstained with a model-authored reason -- not the step-exhaustion
    fallback, and not the verifier dropping every guessed hypothesis."""
    d = r.loop.diagnosis
    reason = d.abstention_reason or ""
    return d.abstained and not reason.startswith(FALLBACK_ABSTENTION_PREFIXES)


def _scenario_record(
    s: Scenario,
    r: EvalResult,
    *,
    pass_idx: int,
    score_mode: str,
    holdout_audits: bool,
    core_flags: dict[str, bool],
    reasoner_usage: dict | None,
    verifier_usage: dict | None,
    wall_s: float,
) -> dict[str, Any]:
    messages = r.loop.messages
    deliberate = _deliberate_abstention(r)
    passed = (deliberate and r.fabrication.ok) if score_mode == "abstain" else r.passed
    final = r.verifier.diagnosis if r.verifier is not None else r.loop.diagnosis
    audit: dict[str, Any] = {"unobserved_args": unobserved_argument_values(messages)}
    if holdout_audits:
        audit["bank_token_args"] = fixtures_bank_argument_leaks(messages)
        audit["train_ts_args"] = train_timestamp_argument_leaks(messages)
    record: dict[str, Any] = {
        "pass": pass_idx,
        "scenario_id": s.id,
        "failure_class": s.failure_class,
        "passed": passed,
        "score_mode": score_mode,
        "judge": {
            "passed": r.judge.passed,
            "correct_cause": r.judge.correct_cause,
            "evidence_matches": r.judge.evidence_matches,
            "reason": r.judge.reason,
        },
        "fabricated": sorted([t, k] for t, k in r.fabrication.fabricated),
        "abstained_final": final.abstained,
        "deliberate_abstained": deliberate,
        "forced_abstention": bool(r.verifier and r.verifier.forced_abstention),
        "verifier_dropped": len(r.verifier.dropped) if r.verifier else 0,
        "steps": r.loop.steps,
        "schema_violations": len(r.loop.schema_violations),
        "tool_calls": [[name, args] for name, args in r.loop.tool_calls],
        "observation_chars": sum(
            len(m["content"])
            for m in messages
            if m["role"] == "user" and m["content"].startswith(_OBS_PREFIX)
        ),
        "reasoner_usage": reasoner_usage,
        "verifier_usage": verifier_usage,
        "wall_s": round(wall_s, 3),
        "audit": audit,
    }
    if s.id in core_flags:
        record["core_overlap"] = core_flags[s.id]
    return record


def _pass_summary(records: list[dict[str, Any]], pass_idx: int) -> dict[str, Any]:
    def _tok(role: str) -> int | None:
        totals = [r[role] for r in records]
        if any(t is None for t in totals):
            return None
        vals = [(t["prompt_tokens"], t["completion_tokens"]) for t in totals]
        if any(p is None or c is None for p, c in vals):
            return None
        return sum(p + c for p, c in vals)

    return {
        "pass": pass_idx,
        "passed": sum(r["passed"] for r in records),
        "fabricating": sum(bool(r["fabricated"]) for r in records),
        "deliberate_abstentions": sum(r["deliberate_abstained"] for r in records),
        "unobserved_arg_violations": sum(
            len(r["audit"]["unobserved_args"]) for r in records
        ),
        "bank_token_violations": sum(
            len(r["audit"].get("bank_token_args", [])) for r in records
        ),
        "train_ts_violations": sum(
            len(r["audit"].get("train_ts_args", [])) for r in records
        ),
        "reasoner_tokens": _tok("reasoner_usage"),
        "verifier_tokens": _tok("verifier_usage"),
        "reasoner_calls": sum(
            (r["reasoner_usage"] or {}).get("calls", 0) for r in records
        ),
        "verifier_calls": sum(
            (r["verifier_usage"] or {}).get("calls", 0) for r in records
        ),
        "wall_s": round(sum(r["wall_s"] for r in records), 3),
    }


def _core_split(
    all_records: list[dict[str, Any]], overlap: bool
) -> dict[str, Any] | None:
    subset = [r for r in all_records if r.get("core_overlap") is overlap]
    if not subset:
        return None
    ids = {r["scenario_id"] for r in subset}
    return {
        "scenarios": len(ids),
        "passed_rate": round(sum(r["passed"] for r in subset) / len(subset), 4),
    }


def main(
    argv: list[str] | None = None,
    *,
    provider: Provider | None = None,
    verifier_provider: Provider | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cell-id", required=True)
    parser.add_argument(
        "--scenarios",
        default="evals/scenarios/fixtures",
        help="scenario dir (holdout/probes are selected EXPLICITLY, DR-0003)",
    )
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument(
        "--out", default=None, help="output dir (default runs/matrix/<cell-id>)"
    )
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--score", choices=("gate", "abstain"), default="gate")
    parser.add_argument(
        "--allow-self-verify",
        action="store_true",
        help="permit verifier model == reasoner model (a deliberate ablation "
        "cell ONLY -- self-verification is otherwise a config error, DR-0020 §8)",
    )
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args(argv)

    scenario_dir = Path(args.scenarios)
    scenarios = [load_scenario(p) for p in sorted(scenario_dir.glob("*.json"))]
    if not scenarios:
        print(f"no scenarios found in {scenario_dir}", file=sys.stderr)
        return 2
    if args.passes < 1:
        print("--passes must be >= 1", file=sys.stderr)
        return 2

    reasoner_model = os.environ.get("QG_MODEL") or None
    verifier_model = os.environ.get("QG_VERIFIER_MODEL") or None
    if args.verify and verifier_provider is None:
        # DR-0020 decision 8: pinned, and never the reasoner verifying itself.
        # The probe runner warns; a matrix cell fails closed. Note this catches
        # only an EXACT model-string match -- two litellm aliases for the same
        # artifact (ollama_chat/X vs ollama/X) would slip past, so pin the
        # verifier to a genuinely different family (the DR's guidance: the BASE
        # artifact) rather than a re-spelling of the reasoner.
        if not verifier_model:
            print(
                "CONFIG ERROR: --verify requires QG_VERIFIER_MODEL to be set "
                "explicitly. The QG_MODEL fallback would let the evaluated "
                "model verify itself (DR-0020 decision 8). Pin the verifier "
                "(e.g. the BASE serving artifact) and re-run.",
                file=sys.stderr,
            )
            return 2
        if (
            verifier_model == (reasoner_model or DEFAULT_MODEL)
            and not args.allow_self_verify
        ):
            print(
                f"CONFIG ERROR: QG_VERIFIER_MODEL == QG_MODEL ({verifier_model!r}) "
                "-- the evaluated model would verify itself (DR-0020 decision 8). "
                "Pin a different verifier, or pass --allow-self-verify for a "
                "deliberate ablation cell.",
                file=sys.stderr,
            )
            return 2
        verifier_provider = default_verifier_provider()
    if provider is None:
        provider = LiteLLMProvider()
        reasoner_model = provider.model

    holdout_audits = all(s.id.startswith("hold_") for s in scenarios)
    core_flags: dict[str, bool] = (
        {} if holdout_audits else {s.id: core_overlaps_train(s) for s in scenarios}
    )

    out_dir = (
        Path(args.out)
        if args.out
        else (Path("runs") / "matrix" / re.sub(r"[^\w.+-]+", "_", args.cell_id))
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear a prior run's artifacts so a shorter re-run (fewer passes) cannot
    # leave orphaned pass_N.jsonl / a stale cell.json behind — a measurement
    # dir must reflect exactly this run. cell.json goes first: its absence is
    # the "incomplete" signal report.py keys on, so it must not survive into a
    # run that then skips before rewriting it.
    (out_dir / "cell.json").unlink(missing_ok=True)
    for stale in out_dir.glob("pass_*.jsonl"):
        stale.unlink()

    started = _now_iso()
    per_pass: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    reasoner_seen = verifier_seen = 0
    try:
        for pass_idx in range(1, args.passes + 1):
            records: list[dict[str, Any]] = []
            pass_path = out_dir / f"pass_{pass_idx}.jsonl"
            with pass_path.open("w", encoding="utf-8") as fh:
                for s in scenarios:
                    t0 = time.monotonic()
                    r = run_scenario(
                        s,
                        provider,
                        verifier_provider=verifier_provider,
                        max_steps=args.max_steps,
                    )
                    wall = time.monotonic() - t0
                    reasoner_usage, reasoner_seen = _usage_delta(
                        provider, reasoner_seen
                    )
                    verifier_usage, verifier_seen = _usage_delta(
                        verifier_provider, verifier_seen
                    )
                    record = _scenario_record(
                        s,
                        r,
                        pass_idx=pass_idx,
                        score_mode=args.score,
                        holdout_audits=holdout_audits,
                        core_flags=core_flags,
                        reasoner_usage=reasoner_usage,
                        verifier_usage=verifier_usage,
                        wall_s=wall,
                    )
                    fh.write(json.dumps(record, default=str) + "\n")
                    fh.flush()
                    records.append(record)
                    mark = "PASS" if record["passed"] else "FAIL"
                    print(
                        f"[{mark}] pass {pass_idx}/{args.passes} {s.id}: "
                        f"steps={record['steps']} "
                        f"fabricated={len(record['fabricated'])} "
                        f"unobserved_args={len(record['audit']['unobserved_args'])} "
                        f"wall={record['wall_s']}s"
                    )
            summary = _pass_summary(records, pass_idx)
            per_pass.append(summary)
            all_records.extend(records)
            print(
                f"pass {pass_idx}: {summary['passed']}/{len(scenarios)} passed; "
                f"{summary['fabricating']} fabricating; "
                f"{summary['unobserved_arg_violations']} unobserved-arg violations"
            )
    except Exception as exc:
        # A backend that cannot be reached or authenticated is a SKIP for the
        # cell (DR-0012 semantics), but distinct from success: no cell.json is
        # written, so a partial run can never be read as a measurement.
        if is_provider_unavailable(exc) or is_auth_error(exc):
            print(
                f"SKIPPED: model backend unavailable/unauthenticated "
                f"({type(exc).__name__}) -- cell incomplete; no cell.json "
                "written (DR-0012).",
                file=sys.stderr,
            )
            return 3
        raise

    n = len(scenarios)
    passed_counts = [p["passed"] for p in per_pass]
    cell = {
        "cell_id": args.cell_id,
        "score_mode": args.score,
        "model": reasoner_model,
        "verify": bool(verifier_provider is not None),
        "verifier_model": verifier_model if args.verify else None,
        "scenarios_dir": str(scenario_dir),
        "scenario_count": n,
        "passes": args.passes,
        "max_steps": args.max_steps,
        "holdout_audits": holdout_audits,
        "git_head": _git_head(),
        "started_at": started,
        "finished_at": _now_iso(),
        "per_pass": per_pass,
        "aggregate": {
            "passed_per_pass": passed_counts,
            "pass_rate_mean": round(sum(passed_counts) / (n * args.passes), 4),
            "passed_min": min(passed_counts),
            "passed_max": max(passed_counts),
            "fabricating_total": sum(p["fabricating"] for p in per_pass),
            "abstain_recall_mean": (
                round(
                    sum(p["deliberate_abstentions"] for p in per_pass)
                    / (n * args.passes),
                    4,
                )
                if args.score == "abstain"
                else None
            ),
            "unobserved_arg_violations_total": sum(
                p["unobserved_arg_violations"] for p in per_pass
            ),
            "bank_token_violations_total": sum(
                p["bank_token_violations"] for p in per_pass
            ),
            "train_ts_violations_total": sum(
                p["train_ts_violations"] for p in per_pass
            ),
            "core_overlapping": _core_split(all_records, True),
            "core_fresh": _core_split(all_records, False),
        },
    }
    (out_dir / "cell.json").write_text(
        json.dumps(cell, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(
        f"\ncell {args.cell_id}: passed per pass {passed_counts} of {n}; "
        f"mean rate {cell['aggregate']['pass_rate_mean']}; "
        f"fabricating {cell['aggregate']['fabricating_total']}; "
        f"wrote {out_dir / 'cell.json'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
