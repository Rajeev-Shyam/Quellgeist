"""Timing-aware verifier variant (Wave 10, T10.1; DR-0024).

An additive, DETERMINISTIC, keyless second axis of verification that targets the
culprit-shifted-*after*-the-errors class the model-driven support verifier
(``agent.verifier``) misses. A cause cannot post-date its effect: if EVERY commit
a hypothesis cites is timestamped strictly after the incident's FIRST error, no
cited commit can be that cause, so the hypothesis is dropped -- and if none
survive, the diagnosis is forced to a graceful abstention.

Why deterministic (folds in the Wave-9 learning, DR-0028): causal ordering is a
timestamp comparison, not a reasoning question, so -- exactly like
``verify_resolution`` -- it stays on the keyless gate and needs NO model. That
also SUPERSEDES the DR-0024 candidate concern about a self-verifying tuned model:
with no model there is nothing to pin and nothing to self-verify (a strict
improvement on the DR-0016 discipline, recorded in the DR).

OPT-IN and additive: it never runs on the frozen eval path unless explicitly
enabled (``QG_TIMING_VERIFY`` / an explicit flag), so the fine-tune's frozen
``0/16 -> 12/16`` comparison stays byte-identical. Conservative in its OWN
direction -- it drops ONLY on a *provable* ordering violation (commit resolvable,
both timestamps parseable, cited commit(s) strictly after the first error);
anything it cannot decide is left to the support verifier and the deterministic
fabrication check. Marking a hypothesis ``supported=True`` here means only "timing
did not rule it out", NOT a positive support claim.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from quellgeist.agent.schema import CommitRef, Diagnosis, Hypothesis
from quellgeist.agent.verifier import HypothesisVerdict, VerifierResult


def _parse_ts(ts: Any) -> datetime | None:
    """Best-effort ISO-8601 parse; ``None`` when unparseable (then timing stays
    silent). Corpus and ingest timestamps are UTC with a trailing ``Z``; we drop
    the ``Z`` and parse naive so every comparison is apples-to-apples."""
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _first_error_ts(logs: list[dict[str, Any]]) -> datetime | None:
    """The earliest parseable ERROR-level log timestamp, or ``None`` when the
    incident has no dated error (then there is no effect to order a cause against)."""
    times = [
        t
        for r in logs
        if str(r.get("level", "")).upper() == "ERROR"
        and (t := _parse_ts(r.get("ts"))) is not None
    ]
    return min(times) if times else None


def _timing_objection(
    hyp: Hypothesis,
    first_err: datetime | None,
    commit_ts: dict[str, datetime],
) -> str | None:
    """A one-line objection when ``hyp`` is timing-impossible, else ``None``.

    Impossible == it cites at least one commit, at least one cited commit resolves
    to a dated commit (so the claim is decidable), and EVERY such resolvable cited
    commit is strictly after the first error. Undecidable cases -- no first error,
    no cited commit, no cited commit resolves, or any cited commit predates/ties
    the first error -- yield ``None`` (no objection)."""
    if first_err is None:
        return None
    cited = [e.ref_id for e in hyp.evidence if isinstance(e, CommitRef)]
    if not cited:
        return None
    resolved = [(sha, commit_ts[sha]) for sha in cited if sha in commit_ts]
    if not resolved:
        return None
    if all(ts > first_err for _, ts in resolved):
        shas = ", ".join(sha for sha, _ in resolved)
        return (
            f"cited commit(s) {shas} are timestamped after the incident's first "
            f"error ({first_err.isoformat()}Z) -- a cause cannot follow its effect"
        )
    return None


def verify_timing(
    diagnosis: Diagnosis,
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
) -> VerifierResult:
    """Drop timing-impossible hypotheses; force abstention if none survive.

    An already-abstaining diagnosis passes through unchanged (abstention is already
    the conservative answer). Returns the (possibly reduced) verified diagnosis plus
    a per-hypothesis verdict list -- ``supported=False`` for a dropped hypothesis,
    ``supported=True`` for one timing could not rule out."""
    if diagnosis.abstained:
        return VerifierResult(diagnosis, [])

    first_err = _first_error_ts(logs)
    commit_ts = {
        c["sha"]: t
        for c in commits
        if "sha" in c and (t := _parse_ts(c.get("ts"))) is not None
    }

    verdicts: list[HypothesisVerdict] = []
    survivors: list[Hypothesis] = []
    for hyp in diagnosis.hypotheses:
        objection = _timing_objection(hyp, first_err, commit_ts)
        if objection is None:
            verdicts.append(HypothesisVerdict(hyp.cause, True, "no timing objection"))
            survivors.append(hyp)
        else:
            verdicts.append(HypothesisVerdict(hyp.cause, False, objection))

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
            "timing verifier dropped all hypotheses: every cited commit post-dates "
            "the incident's first error (a cause cannot follow its effect)"
        ),
        hypotheses=[],
    )
    return VerifierResult(abstained, verdicts)
