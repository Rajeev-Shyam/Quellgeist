"""Judge (Wave 1 STUB).

Keyword/handle match only: top hypothesis must name the gold commit sha, and the
cited handles must include every gold handle. The real LLM-as-judge on a rubric,
validated against a human gold subset, lands in Wave 2. The deterministic
handle-lookup fabrication check (evals/fabrication_check.py) also lands in Wave 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.scenarios.generator import Scenario
from quellgeist.agent.schema import Diagnosis


@dataclass
class JudgeResult:
    passed: bool
    correct_cause: bool
    evidence_matches: bool
    reason: str


def _handle_key(ref) -> tuple[str, object]:
    return (ref.type, ref.sha if ref.type == "commit" else ref.id)


def judge(diagnosis: Diagnosis, scenario: Scenario) -> JudgeResult:
    if diagnosis.abstained:
        return JudgeResult(False, False, False, "diagnosis abstained")

    top = diagnosis.hypotheses[0]
    gold_shas = [r.sha for r in scenario.gold_evidence_refs if r.type == "commit"]
    correct_cause = bool(gold_shas) and all(sha in top.cause for sha in gold_shas)

    cited = {_handle_key(e) for h in diagnosis.hypotheses for e in h.evidence}
    gold = {_handle_key(r) for r in scenario.gold_evidence_refs}
    evidence_matches = gold <= cited

    passed = correct_cause and evidence_matches
    reason = (
        "ok"
        if passed
        else f"correct_cause={correct_cause} evidence_matches={evidence_matches}"
    )
    return JudgeResult(passed, correct_cause, evidence_matches, reason)
