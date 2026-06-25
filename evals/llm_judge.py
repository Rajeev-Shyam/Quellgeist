"""LLM-as-judge on a rubric (Wave 2 -- STUB; logic deferred, see DR-0014).

The planned third reliability layer (DR-0003): a model scores a diagnosis against
the gold on a rubric (correct cause / evidence valid / actions sensible). The
LOGIC is deferred -- it must be validated against a HUMAN-LABELLED gold subset
and tuned to the real reasoner's output before its scores are trusted. It will
NOT replace the deterministic keyword judge (``evals/judge.py``), which stays the
keyless gate (DR-0012). Only the model-agnostic config knob is wired now.

TODO(Wave 2, after the Qwen id-fidelity run + DR-0012):
  - implement ``llm_judge`` returning a rubric verdict (correct_cause /
    evidence_valid / actions_sensible + reason), JSON-action like the loop;
  - build a small human-labelled gold subset and validate judge-vs-human
    agreement before quoting any score.
"""

from __future__ import annotations

import os

from evals.scenarios.generator import Scenario
from quellgeist.agent.providers import DEFAULT_MODEL, LiteLLMProvider, Provider
from quellgeist.agent.schema import Diagnosis


def default_judge_provider() -> Provider:
    """Config knob (wired now): build the judge provider from ``QG_JUDGE_MODEL``
    (falls back to ``QG_MODEL``). The rubric-judge LOGIC is not implemented yet."""
    return LiteLLMProvider(model=os.environ.get("QG_JUDGE_MODEL", DEFAULT_MODEL))


def llm_judge(diagnosis: Diagnosis, scenario: Scenario, provider: Provider):
    """Score a diagnosis on the rubric against the scenario's gold.

    NOT IMPLEMENTED -- deferred until the DR-0012 judge-model decision and a
    human-labelled gold subset (DR-0014). See the module docstring."""
    raise NotImplementedError(
        "LLM-as-judge lands after the DR-0012 decision + a human-labelled gold subset"
    )
