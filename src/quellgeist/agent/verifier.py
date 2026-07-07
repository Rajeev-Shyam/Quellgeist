"""Verifier pass (Wave 2) -- the second reliability layer (DR-0003, DR-0014).

A (stronger) model re-reads each proposed hypothesis against the ACTUAL evidence
it cites and confirms the evidence supports the cause. Unsupported hypotheses are
dropped; if none survive, the diagnosis is forced to a graceful abstention. The
pass checks SUPPORT (semantic) -- existence is the deterministic fabrication
check's job (DR-0013), quality is the judge's. Model-agnostic JSON-action like the
loop (DR-0010); conservative by design (abstain over confirm): an unresolvable
handle or an unparseable verdict counts AGAINST support.

Provider-unavailability (quota / 503 / timeout) is NOT swallowed here -- it
propagates so the eval harness can treat it as a skip, not a false 'unsupported'
(DR-0015). The verifier/judge model is configured, never hard-coded (DR-0012).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from quellgeist.agent.actions import JSONActionError, extract_json
from quellgeist.agent.providers import DEFAULT_MODEL, LiteLLMProvider, Provider
from quellgeist.agent.schema import Diagnosis, Hypothesis


def default_verifier_provider() -> Provider:
    """Build the verifier provider from ``QG_VERIFIER_MODEL`` (falls back to
    ``QG_MODEL``). Intended to be at least as strong as the reasoner."""
    return LiteLLMProvider(model=os.environ.get("QG_VERIFIER_MODEL", DEFAULT_MODEL))


@dataclass
class HypothesisVerdict:
    cause: str
    supported: bool
    reason: str


@dataclass
class VerifierResult:
    # verified diagnosis: unsupported hypotheses dropped; abstains if none survive
    diagnosis: Diagnosis
    verdicts: list[HypothesisVerdict] = field(default_factory=list)

    @property
    def forced_abstention(self) -> bool:
        """True when the verifier turned a confident diagnosis into an abstention
        because no hypothesis survived."""
        return self.diagnosis.abstained and bool(self.verdicts)

    @property
    def dropped(self) -> list[str]:
        return [v.cause for v in self.verdicts if not v.supported]


_SYSTEM = (
    "You are a strict verification reviewer for an incident diagnosis. You are "
    "given ONE proposed root-cause hypothesis and the ACTUAL evidence rows it "
    "cites (resolved from the incident's real logs and commits). Decide whether "
    "that evidence genuinely supports the stated cause. Be conservative: if a "
    "cited row is missing, unrelated, or does not actually demonstrate the cause, "
    "it is NOT supported. Respond with EXACTLY ONE JSON object and nothing else:\n"
    '{"supported": true|false, "reason": "<one short sentence>"}'
)


def _resolve_evidence(
    hyp: Hypothesis,
    logs_by_id: dict[Any, dict],
    commits_by_sha: dict[Any, dict],
    metrics_by_id: dict[Any, dict],
) -> list[dict[str, Any]]:
    """Resolve each cited handle to its actual signal row (or mark it missing)."""
    rows: list[dict[str, Any]] = []
    for ref in hyp.evidence:
        if ref.type == "log":
            row = logs_by_id.get(ref.id)
            rows.append(
                {"handle": f"log:{ref.id}", "found": row is not None, "row": row}
            )
        elif ref.type == "commit":
            row = commits_by_sha.get(ref.sha)
            rows.append(
                {"handle": f"commit:{ref.sha}", "found": row is not None, "row": row}
            )
        elif ref.type == "metric":
            row = metrics_by_id.get(ref.id)
            rows.append(
                {"handle": f"metric:{ref.id}", "found": row is not None, "row": row}
            )
        else:  # pragma: no cover - the discriminated union has no other type
            # Fail closed WITHOUT assuming a `.id` field: a future evidence type
            # (e.g. one keyed by `.sha`) must mark the handle missing, not itself
            # AttributeError inside the fail-closed path.
            key = getattr(ref, "id", None) or getattr(ref, "sha", "?")
            rows.append({"handle": f"{ref.type}:{key}", "found": False, "row": None})
    return rows


def _verdict_for(
    hyp: Hypothesis, evidence_rows: list[dict[str, Any]], provider: Provider
) -> HypothesisVerdict:
    user = (
        f"Cause: {hyp.cause}\n\n"
        f"Cited evidence (resolved against the real signals):\n"
        f"{json.dumps(evidence_rows, default=str)}\n\n"
        "Does the evidence support the cause?"
    )
    text = provider.complete(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
    )
    try:
        obj = extract_json(text)
    except JSONActionError as e:
        return HypothesisVerdict(hyp.cause, False, f"unparseable verifier reply: {e}")
    supported = obj.get("supported")
    if not isinstance(supported, bool):
        return HypothesisVerdict(
            hyp.cause, False, "verifier did not return a boolean 'supported'"
        )
    return HypothesisVerdict(hyp.cause, supported, str(obj.get("reason", "")))


def verify(
    diagnosis: Diagnosis,
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    provider: Provider,
    metrics: list[dict[str, Any]] | None = None,
) -> VerifierResult:
    """Confirm cited evidence supports each hypothesis; drop the unsupported and
    force abstention if none survive. Returns the verified diagnosis + per-
    hypothesis verdicts. An already-abstaining diagnosis passes through unchanged
    (abstention is already the conservative answer)."""
    if diagnosis.abstained:
        return VerifierResult(diagnosis, [])

    logs_by_id = {r["id"]: r for r in logs if "id" in r}
    commits_by_sha = {r["sha"]: r for r in commits if "sha" in r}
    metrics_by_id = {m["metric"]: m for m in (metrics or []) if "metric" in m}

    verdicts: list[HypothesisVerdict] = []
    survivors: list[Hypothesis] = []
    for hyp in diagnosis.hypotheses:
        rows = _resolve_evidence(hyp, logs_by_id, commits_by_sha, metrics_by_id)
        if not any(r["found"] for r in rows):
            # nothing the hypothesis cites resolves to a real signal -> no support,
            # no need to spend a model call.
            verdicts.append(
                HypothesisVerdict(
                    hyp.cause, False, "no cited evidence resolved to a real signal"
                )
            )
            continue
        verdict = _verdict_for(hyp, rows, provider)
        verdicts.append(verdict)
        if verdict.supported:
            survivors.append(hyp)

    if survivors:
        verified = Diagnosis(
            summary=diagnosis.summary,
            abstained=False,
            abstention_reason=None,
            hypotheses=survivors,
            suggested_actions=diagnosis.suggested_actions,
        )
        return VerifierResult(verified, verdicts)

    abstained = Diagnosis(
        abstained=True,
        abstention_reason=(
            "verifier dropped all hypotheses: no cited evidence supported a cause"
        ),
        hypotheses=[],
    )
    return VerifierResult(abstained, verdicts)
