"""Eval harness (Wave 1, Task 9).

Runs the agent against fixture scenarios (canned signals = the injected failure
state) and scores each with the stub judge. Fixtures, not the live demo app, are
the eval substrate: the fixture already bundles the injected logs/commits + gold,
so the eval is reproducible and CI-deterministic. The live app + chaos is the
`quellgeist diagnose` demo path -- a separate concern.

`run_scenario` takes an injected provider so the harness is unit-tested with a
scripted fake (no model, CI-safe). `main` builds the real LiteLLMProvider for a
local real-model run.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from evals.judge import JudgeResult, judge
from evals.scenarios.generator import Scenario, load_scenario
from quellgeist.agent.loop import LoopResult, ToolSpec, run_loop
from quellgeist.agent.providers import LiteLLMProvider, Provider
from quellgeist.servers.filters import filter_log_rows, recent_commits

FIXTURES = Path(__file__).parent / "scenarios" / "fixtures"


def scenario_tools(scenario: Scenario) -> list[ToolSpec]:
    """Serve the scenario's canned signals through the SAME filter logic as the
    real MCP servers, so the agent behaves identically to a live run."""

    def query_logs(since=None, level=None, route=None):
        return filter_log_rows(scenario.logs, since, level, route)

    def get_recent_commits(since=None, limit=None):
        return recent_commits(scenario.commits, since, limit)

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
    ]


@dataclass
class EvalResult:
    scenario_id: str
    judge: JudgeResult
    loop: LoopResult


def run_scenario(
    scenario: Scenario, provider: Provider, *, max_steps: int = 8
) -> EvalResult:
    loop = run_loop(
        provider, scenario_tools(scenario), now=scenario.now, max_steps=max_steps
    )
    return EvalResult(scenario.id, judge(loop.diagnosis, scenario), loop)


def run_all(scenarios: list[Scenario], provider: Provider) -> int:
    passed = 0
    for s in scenarios:
        r = run_scenario(s, provider)
        mark = "PASS" if r.judge.passed else "FAIL"
        print(
            f"[{mark}] {r.scenario_id}: {r.judge.reason} "
            f"(violations={len(r.loop.schema_violations)}, "
            f"cited_but_unseen={r.loop.cited_but_unseen_handles() or '∅'})"
        )
        passed += r.judge.passed
    print(f"\n{passed}/{len(scenarios)} scenarios passed")
    return 0 if passed == len(scenarios) else 1


def _load_all_fixtures() -> list[Scenario]:
    return [load_scenario(p) for p in sorted(FIXTURES.glob("*.json"))]


def main() -> int:
    scenarios = _load_all_fixtures()
    if not scenarios:
        print("no fixtures found", file=sys.stderr)
        return 1
    return run_all(scenarios, LiteLLMProvider())


if __name__ == "__main__":
    raise SystemExit(main())
