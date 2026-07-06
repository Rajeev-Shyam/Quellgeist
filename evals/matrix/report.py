"""Merge matrix ``cell.json`` summaries into the comparison table (Task 4).

    python -m evals.matrix.report runs/matrix/*/cell.json [--out report.md]

Emits GitHub-flavoured markdown: one row per cell with quality (per-pass and
mean pass rates, fabrication, abstain recall for probe cells), measured cost
(tokens and calls per scenario, seconds per scenario), and the DR-0020
decision-8 audit counts. The footer restates the pre-registered claims
wording so a pasted table can never silently oversell: the post-tune fixtures
number is same-bank recombination; the holdout is out-of-vocabulary,
in-structure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _fmt_tokens(total: int | None, n_scenario_runs: int) -> str:
    if total is None or n_scenario_runs == 0:
        return "—"
    return f"{round(total / n_scenario_runs):,}"


def _row(cell: dict[str, Any]) -> str:
    agg = cell["aggregate"]
    n = cell["scenario_count"]
    runs = n * cell["passes"]
    per_pass = ",".join(str(p) for p in agg["passed_per_pass"])
    recall = agg.get("abstain_recall_mean")
    tok_r = sum_or_none(p.get("reasoner_tokens") for p in cell["per_pass"])
    tok_v = sum_or_none(p.get("verifier_tokens") for p in cell["per_pass"])
    calls_r = sum(p.get("reasoner_calls", 0) for p in cell["per_pass"])
    wall = sum(p.get("wall_s", 0.0) for p in cell["per_pass"])
    audits = (
        f"{agg['unobserved_arg_violations_total']}"
        f"/{agg['bank_token_violations_total']}"
        f"/{agg['train_ts_violations_total']}"
    )
    core = ""
    if agg.get("core_overlapping") and agg.get("core_fresh"):
        core = (
            f"overlap {agg['core_overlapping']['passed_rate']:.2f} "
            f"(n={agg['core_overlapping']['scenarios']}) / "
            f"fresh {agg['core_fresh']['passed_rate']:.2f} "
            f"(n={agg['core_fresh']['scenarios']})"
        )
    return (
        f"| {cell['cell_id']} "
        f"| {cell.get('model') or '—'} "
        f"| {cell.get('verifier_model') or ('on' if cell.get('verify') else 'off')} "
        f"| {Path(cell['scenarios_dir']).name} ({n}) "
        f"| {per_pass} /{n} "
        f"| {agg['pass_rate_mean']:.2f} "
        f"| {agg['fabricating_total']} "
        f"| {'—' if recall is None else f'{recall:.2f}'} "
        f"| {audits} "
        f"| {_fmt_tokens(tok_r, runs)} "
        f"| {_fmt_tokens(tok_v, runs)} "
        f"| {round(calls_r / runs, 1) if runs else '—'} "
        f"| {round(wall / runs, 1) if runs else '—'} "
        f"| {core} |"
    )


def sum_or_none(values) -> int | None:
    vals = list(values)
    if not vals or any(v is None for v in vals):
        return None
    return sum(vals)


_HEADER = (
    "| cell | model | verifier | set (n) | passed/pass | mean rate | fab "
    "| abstain recall | audits u/b/t | reasoner tok/scen | verifier tok/scen "
    "| calls/scen | s/scen | fixtures core split |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)

_FOOTER = (
    "\nAudit columns: u = unobserved tool-call argument values, b = "
    "fixtures-bank tokens in holdout filter arguments, t = train-seen "
    "timestamps as unobserved holdout arguments (DR-0020 decision 8; b/t are "
    "0 by construction on non-holdout cells, where those audits are off).\n\n"
    "Claims wording (pre-registered, DR-0020 decision 8): the post-tune "
    "FIXTURES number measures *same-bank recombination* (report it split "
    "core-overlapping vs core-fresh); the HOLDOUT is *out-of-vocabulary, "
    "in-structure* — a holdout win supports exactly one claim: the tuned "
    "model executes the broad-first, copy-from-observation policy on tokens "
    "it has never seen. No cell supports claims about unseen incident "
    "structure or real incidents.\n"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cells", nargs="+", help="paths to cell.json files")
    parser.add_argument("--out", default=None, help="write markdown here too")
    args = parser.parse_args(argv)

    cells: list[dict[str, Any]] = []
    for path in args.cells:
        p = Path(path)
        if not p.is_file():
            print(
                f"MISSING: {p} — that cell never completed (run_cell writes "
                "cell.json only on completion); re-run it before reporting.",
                file=sys.stderr,
            )
            return 1
        cells.append(json.loads(p.read_text(encoding="utf-8")))

    lines = [
        "# Wave-4 comparison matrix",
        "",
        _HEADER,
        *(_row(c) for c in sorted(cells, key=lambda c: c["cell_id"])),
        _FOOTER,
    ]
    text = "\n".join(lines)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
