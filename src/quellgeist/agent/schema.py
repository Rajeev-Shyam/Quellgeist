"""Shared diagnosis contract (DR-0009).

The agent loop returns a `Diagnosis`, the postmortem renderer reads it, and the
Wave 2 deterministic fabrication check verifies it. Evidence is cited ONLY as
structured handles (`LogRef.id` / `CommitRef.sha` / `MetricRef.id`) — never free
text. The handle id/sha is what gets checked; `note` is display-only gloss.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class _EvidenceRefKey:
    """Canonical handle accessors for every evidence type, so the ~a-half-dozen
    call sites that used to re-derive ``(type, sha-or-id)`` by hand share one
    definition. These are PROPERTIES, not pydantic fields, so they do not change
    the model's JSON schema or serialization (the fine-tune's prompt is unchanged).
    Each concrete type provides ``type`` (the discriminator) and ``ref_id`` (the
    checked value); ``key`` is the membership handle both the loop and the
    deterministic fabrication check look up."""

    @property
    def key(self) -> tuple[str, int | str]:
        return (self.type, self.ref_id)  # type: ignore[attr-defined]


class LogRef(_EvidenceRefKey, BaseModel):
    """Reference to one structured-log row by its source-stable id."""

    type: Literal["log"] = "log"
    id: int  # source-stable ingest/line counter, NOT a filtered-result index  (checked)
    note: str = (
        ""  # display-only human gloss                                         (NOT checked)
    )

    @property
    def ref_id(self) -> int:
        return self.id


class CommitRef(_EvidenceRefKey, BaseModel):
    """Reference to a git commit by SHA."""

    type: Literal["commit"] = "commit"
    sha: str  # (checked)
    note: str = ""  # display-only  (NOT checked)

    @property
    def ref_id(self) -> str:
        return self.sha


class MetricRef(_EvidenceRefKey, BaseModel):
    """Reference to a metric series. Emitted from Wave 3 onward."""

    type: Literal["metric"] = "metric"
    id: str  # (checked once the Wave 3 fabrication check handles it)
    note: str = ""

    @property
    def ref_id(self) -> str:
        return self.id


EvidenceRef = Annotated[
    LogRef | CommitRef | MetricRef,
    Field(discriminator="type"),
]


class Hypothesis(BaseModel):
    cause: str
    confidence: float = Field(ge=0.0, le=1.0)  # advisory; list is pre-sorted best-first
    evidence: list[EvidenceRef] = Field(min_length=1)  # every cause cites >=1 handle


class Diagnosis(BaseModel):
    summary: str = ""
    abstained: bool = False
    abstention_reason: str | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _abstention_invariant(self) -> Diagnosis:
        if self.abstained:
            if not self.abstention_reason:
                raise ValueError(
                    "abstained=True requires a non-empty abstention_reason"
                )
            if self.hypotheses:
                raise ValueError(
                    "abstained=True is incompatible with a non-empty hypotheses list"
                )
        elif not self.hypotheses:
            raise ValueError(
                "a non-abstained Diagnosis must contain at least one hypothesis"
            )
        return self
