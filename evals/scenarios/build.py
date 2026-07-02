"""Regenerate the fixture + holdout scenario corpora (Wave 3).

``python -m evals.scenarios.build`` rewrites ``evals/scenarios/fixtures/`` (the
eval corpus ``run_evals.main`` runs) and ``evals/scenarios/holdout/`` (reserved --
a DIFFERENT distribution, DR-0003) from ``generator.generate_scenarios``.

Deterministic and idempotent: re-running leaves ``git`` clean. The hand-authored
``bad_deploy_0001.json`` is preserved (the generator uses id 0002+); any other
stale generated file is removed so a count change doesn't leave orphans.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.scenarios.generator import Scenario, generate_scenarios

_HERE = Path(__file__).parent
_FIXTURES = _HERE / "fixtures"
_HOLDOUT = _HERE / "holdout"
_ANCHOR = "bad_deploy_0001.json"  # hand-authored; never overwritten or removed


def scenario_json(s: Scenario) -> str:
    """Serialise a Scenario to the clean fixture shape (matches the anchor: no
    display-only ``note``, no legacy ``gold_evidence`` field). Public: the
    DR-0020 probe sets are written in this same shape, so the serialization is
    a cross-corpus contract with a single owner."""
    refs = [
        (
            {"type": r.type, "sha": r.sha}
            if r.type == "commit"
            else {"type": r.type, "id": r.id}
        )
        for r in s.gold_evidence_refs
    ]
    doc: dict[str, Any] = {
        "id": s.id,
        "failure_class": s.failure_class,
        "now": s.now,
        "logs": s.logs,
        "commits": s.commits,
    }
    if s.metrics:  # resource_exhaustion only; omitted for the log+commit classes
        doc["metrics"] = s.metrics
    doc["gold_cause"] = s.gold_cause
    doc["gold_evidence_refs"] = refs
    return json.dumps(doc, indent=2) + "\n"


def write_split(
    scenarios: list[Scenario], dest: Path, *, keep: frozenset[str] = frozenset()
) -> None:
    """Idempotently write one scenario dir: stale generated files are removed
    (``keep`` protects hand-authored ones). Public for the same reason as
    ``scenario_json`` — the DR-0020 probe dirs are written through it."""
    dest.mkdir(parents=True, exist_ok=True)
    written = {f"{s.id}.json" for s in scenarios} | keep
    for existing in dest.glob("*.json"):
        if existing.name not in written:
            existing.unlink()
    for s in scenarios:
        (dest / f"{s.id}.json").write_text(scenario_json(s), encoding="utf-8")


def main() -> None:
    fixtures = generate_scenarios("fixtures")
    holdout = generate_scenarios("holdout")
    write_split(fixtures, _FIXTURES, keep=frozenset({_ANCHOR}))
    write_split(holdout, _HOLDOUT)
    print(f"wrote {len(fixtures)} fixtures (+1 hand-authored anchor) to {_FIXTURES}")
    print(f"wrote {len(holdout)} holdout scenarios to {_HOLDOUT}")


if __name__ == "__main__":
    main()
