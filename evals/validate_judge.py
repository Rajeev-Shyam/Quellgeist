"""Validate the advisory LLM-judge against a human-labelled gold subset (DR-0018).

The LLM-judge (``evals/llm_judge.py``) is advisory: its rubric scores cannot be
quoted until we know it AGREES with human judgment (DR-0003). This harness runs
the judge over a hand-labelled set of (scenario, diagnosis, human verdict) cases
spanning the three failure classes and reports judge-vs-human agreement -- overall
verdict, per rubric field, and Cohen's kappa.

Use a judge model DIFFERENT from (ideally stronger than) the reasoner via
``QG_JUDGE_MODEL`` -- otherwise the model grades its own family and the number is
self-assessment, not validation (DR-0017). This is a REPORTING tool: it never
gates. Key-gated like the eval; an unreachable/rejected backend is a SKIP
(DR-0012/DR-0015), not a failure.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.llm_judge import RubricVerdict, default_judge_provider, llm_judge
from evals.scenarios.generator import Scenario
from quellgeist.agent.providers import (
    Provider,
    is_auth_error,
    is_provider_unavailable,
)
from quellgeist.agent.schema import Diagnosis

CASES_PATH = Path(__file__).parent / "judge_validation" / "labelled_cases.json"


@dataclass(frozen=True)
class LabelledCase:
    id: str
    scenario: Scenario
    diagnosis: Diagnosis
    human_correct_cause: bool
    human_evidence_valid: bool
    human_pass: bool  # the human verdict: correct_cause AND evidence_valid
    rationale: str


def load_cases(path: str | Path = CASES_PATH) -> list[LabelledCase]:
    """Load the labelled subset. Scenarios are shared and referenced by key; each
    case pairs a diagnosis with the human verdict."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios = {k: Scenario.model_validate(v) for k, v in doc["scenarios"].items()}
    cases: list[LabelledCase] = []
    for c in doc["cases"]:
        h = c["human"]
        cases.append(
            LabelledCase(
                id=c["id"],
                scenario=scenarios[c["scenario"]],
                diagnosis=Diagnosis.model_validate(c["diagnosis"]),
                human_correct_cause=bool(h["correct_cause"]),
                human_evidence_valid=bool(h["evidence_valid"]),
                human_pass=h["verdict"] == "pass",
                rationale=c.get("rationale", ""),
            )
        )
    return cases


@dataclass
class CaseResult:
    case: LabelledCase
    verdict: RubricVerdict

    @property
    def judge_pass(self) -> bool:
        return self.verdict.passed

    @property
    def verdict_agree(self) -> bool:
        return self.judge_pass == self.case.human_pass

    @property
    def cc_agree(self) -> bool:
        return self.verdict.correct_cause == self.case.human_correct_cause

    @property
    def ev_agree(self) -> bool:
        return self.verdict.evidence_valid == self.case.human_evidence_valid


def cohen_kappa(human: list[bool], judge: list[bool]) -> float:
    """Cohen's kappa for two binary raters -- agreement corrected for chance.
    1.0 = perfect, 0.0 = chance-level, negative = worse than chance."""
    n = len(human)
    if n == 0:
        return 0.0
    po = sum(h == j for h, j in zip(human, judge, strict=True)) / n
    hp = sum(human) / n
    jp = sum(judge) / n
    pe = hp * jp + (1 - hp) * (1 - jp)  # expected agreement by chance
    if pe >= 1.0:  # a rater is constant -> kappa undefined; report po as 0/1
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


@dataclass
class AgreementReport:
    results: list[CaseResult]

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def verdict_agreement(self) -> int:
        return sum(r.verdict_agree for r in self.results)

    @property
    def cc_agreement(self) -> int:
        return sum(r.cc_agree for r in self.results)

    @property
    def ev_agreement(self) -> int:
        return sum(r.ev_agree for r in self.results)

    @property
    def kappa(self) -> float:
        return cohen_kappa(
            [r.case.human_pass for r in self.results],
            [r.judge_pass for r in self.results],
        )

    @property
    def disagreements(self) -> list[CaseResult]:
        return [r for r in self.results if not r.verdict_agree]


def run_validation(cases: list[LabelledCase], provider: Provider) -> AgreementReport:
    """Run the LLM-judge on every case and collect verdicts. Provider errors
    propagate so the caller can treat them as a skip (DR-0015)."""
    return AgreementReport(
        [CaseResult(c, llm_judge(c.diagnosis, c.scenario, provider)) for c in cases]
    )


def _print_report(report: AgreementReport, model_desc: str) -> None:
    def pct(x: int) -> str:
        return f"{x}/{report.n} ({x / report.n:.2f})" if report.n else "0/0"

    print(f"judge model = {model_desc}")
    print(f"labelled cases: {report.n}")
    print(f"verdict agreement:         {pct(report.verdict_agreement)}")
    print(f"  correct_cause agreement:  {pct(report.cc_agreement)}")
    print(f"  evidence_valid agreement: {pct(report.ev_agreement)}")
    print(f"Cohen's kappa (verdict):   {report.kappa:.2f}")
    if report.disagreements:
        print("disagreements (human vs judge):")
        for r in report.disagreements:
            h = "pass" if r.case.human_pass else "fail"
            j = "pass" if r.judge_pass else "fail"
            print(f"  - {r.case.id}: human={h} judge={j} :: {r.verdict.reason}")
    else:
        print("no disagreements -- the judge matches the human on every case.")


def main(provider: Provider | None = None) -> int:
    cases = load_cases()
    if provider is None:
        if not os.environ.get("QG_JUDGE_MODEL"):
            print(
                "WARNING: QG_JUDGE_MODEL is unset, so the judge defaults to the "
                "reasoner model -- this measures SELF-agreement, not independent "
                "validation (DR-0017). Set QG_JUDGE_MODEL to a different/stronger "
                "model for a trustworthy number.",
                file=sys.stderr,
            )
        provider = default_judge_provider()
    model_desc = getattr(provider, "model", type(provider).__name__)
    try:
        report = run_validation(cases, provider)
    except Exception as exc:
        # Reporting job: an unreachable/rejected judge backend is a SKIP, not a
        # failure -- it must not redden CI (DR-0012/DR-0015). Genuine bugs re-raise.
        if is_provider_unavailable(exc):
            print(
                f"SKIPPED: judge backend unavailable ({type(exc).__name__}) -- "
                "quota/availability, not a validation failure (DR-0012).",
                file=sys.stderr,
            )
            return 0
        if is_auth_error(exc):
            print(
                f"SKIPPED: judge backend rejected the credentials "
                f"({type(exc).__name__}) -- fix the key/secret (DR-0017).",
                file=sys.stderr,
            )
            return 0
        raise
    _print_report(report, model_desc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
