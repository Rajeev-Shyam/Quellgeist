"""Scenario schema + loader (Wave 1, Task 9 stub).

A Scenario bundles an injected failure's canned signals (logs, commits) with the
gold root cause and the gold evidence handles a correct diagnosis must cite. In
Wave 1 we load one hand-authored fixture; Wave 3 turns this into parameterised
generation (templates -> ~50 variants across failure classes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from quellgeist.agent.schema import EvidenceRef


class Scenario(BaseModel):
    id: str
    failure_class: str
    now: str
    logs: list[dict[str, Any]] = Field(default_factory=list)
    commits: list[dict[str, Any]] = Field(default_factory=list)
    gold_cause: str
    gold_evidence: list[str] = Field(
        default_factory=list
    )  # legacy free-text; unused by harness
    gold_evidence_refs: list[EvidenceRef] = Field(default_factory=list)


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate_json(Path(path).read_text(encoding="utf-8"))


def generate_scenarios() -> list[Scenario]:  # Wave 3
    raise NotImplementedError("parameterised scenario generation lands in Wave 3")
