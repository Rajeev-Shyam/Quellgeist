"""Postmortem renderer (Wave 1, Task 7).

Pure render of a Diagnosis into a templated Markdown postmortem -- deterministic
and model-free, so it is fully unit-testable. Evidence is rendered as its
structured handle (log #id / commit sha / metric id) PLUS its note, so each
citation is both human-readable and traceable back to the real signal (DR-0009).
The abstained case is rendered explicitly rather than as an empty report.

A timeline section is deliberately omitted in v1: a Diagnosis carries evidence
*handles*, not timestamps, so a faithful timeline needs the handles resolved back
to their source rows -- a small follow-on once the loop passes resolved evidence
through, not something to fabricate here.
"""

from __future__ import annotations

from pathlib import Path

from quellgeist.agent.schema import Diagnosis, EvidenceRef


def _render_evidence(ref: EvidenceRef) -> str:
    if ref.type == "commit":
        head = f"commit {ref.sha}"
    elif ref.type == "metric":
        head = f"metric {ref.id}"
    else:  # log
        head = f"log #{ref.id}"
    return f"{head} — {ref.note}" if ref.note else head


def render_postmortem(
    diagnosis: Diagnosis, *, title: str = "Incident Postmortem"
) -> str:
    lines: list[str] = [f"# {title}", ""]

    if diagnosis.summary:
        lines += ["## Summary", diagnosis.summary, ""]

    if diagnosis.abstained:
        lines += [
            "## Insufficient evidence",
            "The agent did not find enough evidence to name a confident root cause.",
            "",
            f"Reason: {diagnosis.abstention_reason}",
            "",
        ]
        return "\n".join(lines).rstrip() + "\n"

    lines += ["## Root-cause hypotheses", ""]
    for i, h in enumerate(diagnosis.hypotheses, start=1):
        lines.append(f"### {i}. {h.cause}  (confidence: {h.confidence:.2f})")
        lines.append("")
        lines.append("Evidence:")
        lines += [f"- {_render_evidence(ref)}" for ref in h.evidence]
        lines.append("")

    if diagnosis.suggested_actions:
        lines += ["## Suggested actions", ""]
        lines += [f"- {a}" for a in diagnosis.suggested_actions]
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_postmortem(
    diagnosis: Diagnosis, path: str | Path, *, title: str = "Incident Postmortem"
) -> Path:
    p = Path(path)
    p.write_text(render_postmortem(diagnosis, title=title), encoding="utf-8")
    return p
