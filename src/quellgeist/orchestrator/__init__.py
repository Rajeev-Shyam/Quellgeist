"""quellgeist.orchestrator — resumable investigation around the FROZEN loop. SCAFFOLD (Wave 7–9).

Not yet implemented. Per [DR-0023](../../../docs/quellgeist-adr-log.md) decisions
5 & 6 and the [v2 spec](../../../docs/quellgeist-v2-spec.md) §Components. This is the
ONLY place that knows about hints, the review gate, and resolution re-check — and it
calls ``agent.loop.run_loop`` **unchanged** (the measured artifact is never edited;
HITL is orchestration *around* it, never inside it).

Planned surface:
- ``investigate(incident, signals, *, hint=None) -> RunRecord`` — default path calls
  ``run_loop`` exactly as the CLI does, then the deterministic fabrication check +
  the (optionally timing-aware) verifier, then ``pending_review``.
- ``resume_after_review(run_id, decision, steer=None) -> RunRecord`` (Wave 8).
- ``verify_resolution(incident, run_id) -> ResolutionVerdict`` (Wave 9, sandbox only —
  no production mutation; DR-0001 boundary holds).

**Frozen-path rule:** a hint is an extra *operator* message added around the loop; it
never edits the system prompt or the ``Observation from …:`` / retry strings. If
between-steps injection would touch those, fall back to trigger-time hints only.
"""

from __future__ import annotations

__all__: list[str] = []
