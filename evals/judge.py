"""Deterministic keyword/handle judge -- the keyless eval gate (DR-0012, DR-0016).

Two deterministic checks: (1) ``correct_cause`` -- the top hypothesis pins the
blame on the gold commit, cited as a structured evidence handle (DR-0009); and
(2) ``evidence_matches`` -- every gold handle is cited. With the fabrication check
this is the keyless gate; the semantic LLM-as-judge (``evals/llm_judge.py``) is the
advisory layer. ``correct_cause`` checks the cited HANDLE, not the prose: an earlier
``sha in cause_text`` check false-failed a correct diagnosis that (correctly) cited
the commit as a handle on the first real run -- see DR-0017.
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
    gold_shas = {r.sha for r in scenario.gold_evidence_refs if r.type == "commit"}
    # The TOP hypothesis must pin the gold commit, cited as a structured handle
    # (DR-0009) -- NOT pasted into the prose. The old `sha in top.cause` check was
    # a false-negative on a correct, commit-citing diagnosis the first real run
    # produced (DR-0017). Semantic correctness of the prose is the LLM-judge's job.
    top_commit_shas = {e.sha for e in top.evidence if e.type == "commit"}
    correct_cause = bool(gold_shas) and gold_shas <= top_commit_shas

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
