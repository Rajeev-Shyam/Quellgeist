"""LLM-as-judge on a rubric (Wave 2) -- the third reliability layer (DR-0003).

Scores a diagnosis against the scenario's gold on a rubric: did it name the right
cause, is the cited evidence valid, are the suggested actions sensible. Model-
agnostic JSON-action (DR-0010).

PROVISIONAL + key-gated: this does NOT gate the eval. The deterministic keyword
judge (``evals/judge.py``) + the fabrication check (``evals/fabrication_check.py``)
remain the keyless gate; the rubric scores are advisory and must NOT be quoted as
validated until checked against a human-labelled gold subset (DR-0003/DR-0014).
Provider-unavailability propagates (DR-0015); an unparseable reply scores 0.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from evals.scenarios.generator import Scenario
from quellgeist.agent.actions import JSONActionError, extract_json
from quellgeist.agent.providers import DEFAULT_MODEL, LiteLLMProvider, Provider
from quellgeist.agent.schema import Diagnosis


def default_judge_provider() -> Provider:
    """Build the judge provider from ``QG_JUDGE_MODEL`` (falls back to ``QG_MODEL``)."""
    return LiteLLMProvider(model=os.environ.get("QG_JUDGE_MODEL", DEFAULT_MODEL))


@dataclass
class RubricVerdict:
    correct_cause: bool
    evidence_valid: bool
    actions_sensible: bool
    score: float  # the model's overall rubric score, clamped to [0, 1]
    reason: str
    parsed: bool = True  # False when the model reply could not be parsed (scored 0)

    @property
    def passed(self) -> bool:
        """The rubric's core bar: right cause backed by valid evidence. Advisory
        only -- NOT the eval gate (that stays deterministic until validated)."""
        return self.correct_cause and self.evidence_valid


_SYSTEM = (
    "You are an expert SRE grading an incident diagnosis against the known gold "
    "answer. Score three criteria, then give an overall score in [0,1]: "
    "correct_cause (does the top hypothesis identify the gold root cause?), "
    "evidence_valid (is the cited evidence real and relevant?), actions_sensible "
    "(are the suggested actions reasonable?). An abstention when the gold has a "
    "clear cause is incorrect. Be strict and fair. Respond with EXACTLY ONE JSON "
    "object and nothing else:\n"
    '{"correct_cause": true|false, "evidence_valid": true|false, '
    '"actions_sensible": true|false, "score": 0.0, "reason": "<one short sentence>"}'
)


def _gold_block(scenario: Scenario) -> str:
    gold_refs = [
        {"type": r.type, "id": (r.sha if r.type == "commit" else r.id)}
        for r in scenario.gold_evidence_refs
    ]
    return json.dumps(
        {"gold_cause": scenario.gold_cause, "gold_evidence": gold_refs}, default=str
    )


def llm_judge(
    diagnosis: Diagnosis, scenario: Scenario, provider: Provider
) -> RubricVerdict:
    """Score a diagnosis on the rubric against the scenario's gold. An unparseable
    reply scores 0 with ``parsed=False``."""
    user = (
        f"Gold answer for scenario {scenario.id} (failure class "
        f"{scenario.failure_class}):\n{_gold_block(scenario)}\n\n"
        f"Diagnosis to grade:\n{diagnosis.model_dump_json()}\n\n"
        "Grade it on the rubric."
    )
    text = provider.complete(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
    )
    try:
        obj = extract_json(text)
    except JSONActionError as e:
        return RubricVerdict(
            False, False, False, 0.0, f"unparseable judge reply: {e}", parsed=False
        )

    try:
        score = float(obj.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return RubricVerdict(
        correct_cause=bool(obj.get("correct_cause", False)),
        evidence_valid=bool(obj.get("evidence_valid", False)),
        actions_sensible=bool(obj.get("actions_sensible", False)),
        score=max(0.0, min(1.0, score)),
        reason=str(obj.get("reason", "")),
    )
