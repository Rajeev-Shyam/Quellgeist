"""Eval harness (Wave 1, Task 9; fabrication gate added Wave 2).

Runs the agent against fixture scenarios (canned signals = the injected failure
state) and scores each with the judge AND the deterministic fabrication check: a
scenario passes only if the judge passes and the diagnosis cites no evidence
absent from the real signals (the zero-fabricated-causes guarantee). Fixtures,
not the live demo app, are the eval substrate: the fixture already bundles the
injected logs/commits + gold, so the eval is reproducible and CI-deterministic.
The live app + chaos is the `quellgeist diagnose` demo path -- a separate concern.

`run_scenario` takes an injected provider so the harness is unit-tested with a
scripted fake (no model, CI-safe). `main` builds the real LiteLLMProvider for a
local real-model run.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.fabrication_check import FabricationResult, check_fabrication
from evals.judge import JudgeResult, judge
from evals.llm_judge import RubricVerdict, default_judge_provider, llm_judge
from evals.scenarios.generator import Scenario, load_scenario
from quellgeist.agent.loop import LoopResult, ToolSpec, run_loop
from quellgeist.agent.providers import (
    LiteLLMProvider,
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.agent.verifier import (
    VerifierResult,
    default_verifier_provider,
    verify,
)
from quellgeist.servers.filters import (
    filter_log_rows,
    filter_metric_rows,
    recent_commits,
)

FIXTURES = Path(__file__).parent / "scenarios" / "fixtures"


def scenario_tools(scenario: Scenario) -> list[ToolSpec]:
    """Serve the scenario's canned signals through the SAME filter logic as the
    real MCP servers, so the agent behaves identically to a live run."""

    def query_logs(since=None, level=None, route=None):
        return filter_log_rows(scenario.logs, since, level, route)

    def get_recent_commits(since=None, limit=None):
        return recent_commits(scenario.commits, since, limit)

    def query_metrics(name=None, since=None):
        return filter_metric_rows(scenario.metrics, name, since)

    return [
        ToolSpec(
            "query_logs",
            "Query structured incident logs; optional since/level/route; rows carry a stable int id.",
            query_logs,
        ),
        ToolSpec(
            "get_recent_commits",
            "List recent deploys newest-first; optional since/limit; commits carry sha/ts/msg/files.",
            get_recent_commits,
        ),
        ToolSpec(
            "query_metrics",
            "Query metric time-series (memory/connections/queue depth) for resource "
            "incidents; optional name/since; each series carries a `metric` name "
            "(cite it), `unit`, and `points`.",
            query_metrics,
        ),
    ]


@dataclass
class EvalResult:
    scenario_id: str
    judge: JudgeResult
    loop: LoopResult
    fabrication: FabricationResult
    verifier: VerifierResult | None = None  # set when the verifier pass ran
    rubric: RubricVerdict | None = None  # set when the LLM-judge ran (advisory)

    @property
    def passed(self) -> bool:
        """The reliability bar: a judged-correct diagnosis that fabricates
        nothing. A cited-but-nonexistent handle fails the scenario even when the
        judge would otherwise pass it -- zero fabricated causes is the headline
        guarantee, checked deterministically against the full signal set. The
        keyword judge + fabrication check (both keyless) are the gate; the
        verifier shapes the diagnosis they score, the LLM rubric is advisory only."""
        return self.judge.passed and self.fabrication.ok


def run_scenario(
    scenario: Scenario,
    provider: Provider,
    *,
    verifier_provider: Provider | None = None,
    judge_provider: Provider | None = None,
    max_steps: int = 8,
) -> EvalResult:
    loop = run_loop(
        provider, scenario_tools(scenario), now=scenario.now, max_steps=max_steps
    )
    diagnosis = loop.diagnosis

    # Optional verifier pass: confirm cited evidence supports each hypothesis and
    # force abstention otherwise. The VERIFIED diagnosis is what gets scored.
    verifier_result: VerifierResult | None = None
    if verifier_provider is not None:
        verifier_result = verify(
            diagnosis,
            scenario.logs,
            scenario.commits,
            verifier_provider,
            scenario.metrics,
        )
        diagnosis = verifier_result.diagnosis

    # Optional LLM-judge (advisory rubric; does not gate -- see EvalResult.passed).
    rubric: RubricVerdict | None = None
    if judge_provider is not None:
        rubric = llm_judge(diagnosis, scenario, judge_provider)

    return EvalResult(
        scenario.id,
        judge(diagnosis, scenario),
        loop,
        check_fabrication(diagnosis, scenario.logs, scenario.commits, scenario.metrics),
        verifier=verifier_result,
        rubric=rubric,
    )


def run_all(
    scenarios: list[Scenario],
    provider: Provider,
    *,
    verifier_provider: Provider | None = None,
    judge_provider: Provider | None = None,
) -> int:
    passed = fabricating = 0
    for s in scenarios:
        r = run_scenario(
            s,
            provider,
            verifier_provider=verifier_provider,
            judge_provider=judge_provider,
        )
        mark = "PASS" if r.passed else "FAIL"
        fab = ", ".join(f"{t}:{k}" for t, k in sorted(r.fabrication.fabricated))
        extra = ""
        if r.verifier is not None:
            extra += f", verifier_dropped={len(r.verifier.dropped)}"
        if r.rubric is not None:
            verdict = "pass" if r.rubric.passed else "fail"
            extra += f", rubric={verdict}({r.rubric.score:.2f})"
        print(
            f"[{mark}] {r.scenario_id}: {r.judge.reason} "
            f"(violations={len(r.loop.schema_violations)}, fabricated={fab or '∅'}{extra})"
        )
        passed += r.passed
        fabricating += not r.fabrication.ok
    n = len(scenarios)
    print(f"\n{passed}/{n} scenarios passed; {fabricating} with fabricated evidence")
    return 0 if passed == n else 1


def _load_all_fixtures() -> list[Scenario]:
    # QG_SCENARIOS_DIR points the run at a different scenario set -- notably
    # evals/scenarios/holdout/, the reserved different-distribution set
    # (DR-0003). The holdout is deliberately NOT globbed by default so casual
    # runs and prompt iteration never touch it; selecting it is an explicit act.
    directory = Path(os.environ.get("QG_SCENARIOS_DIR") or FIXTURES)
    return [load_scenario(p) for p in sorted(directory.glob("*.json"))]


def main(
    provider: Provider | None = None,
    *,
    verifier_provider: Provider | None = None,
    judge_provider: Provider | None = None,
) -> int:
    scenarios = _load_all_fixtures()
    if not scenarios:
        where = os.environ.get("QG_SCENARIOS_DIR") or str(FIXTURES)
        print(f"no scenarios found in {where}", file=sys.stderr)
        return 1
    # Opt-in reliability layers, key-gated; model from QG_VERIFIER_MODEL /
    # QG_JUDGE_MODEL (fall back to QG_MODEL). Off unless explicitly enabled.
    if verifier_provider is None and os.environ.get("QG_VERIFY") == "1":
        verifier_provider = default_verifier_provider()
    if judge_provider is None and os.environ.get("QG_JUDGE_LLM") == "1":
        judge_provider = default_judge_provider()
    try:
        return run_all(
            scenarios,
            provider or LiteLLMProvider(),
            verifier_provider=verifier_provider,
            judge_provider=judge_provider,
        )
    except Exception as exc:
        # An unreachable backend (free-tier quota / 503 / timeout) is a SKIP, not
        # a reliability failure: it must not redden CI (DR-0012). A model that
        # RAN and produced a bad diagnosis returns 1 from run_all above -- that is
        # a real failure and still reddens. Re-raise anything else (real bugs).
        if is_provider_unavailable(exc):
            print(
                f"SKIPPED: model backend unavailable ({type(exc).__name__}) -- "
                "quota/availability, not a reliability failure (DR-0012). The "
                "keyless deterministic gate is the reliability gate.",
                file=sys.stderr,
            )
            return 0
        if is_auth_error(exc):
            # A missing / invalid / expired key (e.g. a stale CI secret) is a
            # credential problem, not an eval failure -- skip, don't redden the
            # non-gating reporting job (DR-0012/DR-0015). Fix the key/secret.
            print(
                f"SKIPPED: model backend rejected the credentials "
                f"({type(exc).__name__}) -- fix the key/secret. Not a reliability "
                "failure (DR-0012); the keyless deterministic gate is the gate.",
                file=sys.stderr,
            )
            return 0
        raise


if __name__ == "__main__":
    raise SystemExit(main())
