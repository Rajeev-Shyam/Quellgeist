"""Evidence-gathering agent loop (Wave 1, Task 6).

A legible, model-agnostic JSON-action ReAct loop: decide -> call tool -> observe
-> repeat, then emit a structured ``Diagnosis``. The model never uses a backend's
native function-calling; it emits JSON actions as text and we parse them, so the
loop is identical on Gemini and on a local 4-bit Qwen (DR-0008).

Returns a ``LoopResult`` (not a bare Diagnosis) because DR-0009 calls for an
early read on citation fidelity: the result carries the diagnosis plus the trace
needed to measure it -- schema violations and which evidence handles the model
cited versus actually saw. Enforcement of fabrication (the deterministic check +
verifier) is Wave 2; here we only measure.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from quellgeist.agent.actions import JSONActionError as _ParseError
from quellgeist.agent.actions import extract_json as _extract_json
from quellgeist.agent.prompts import build_system_prompt, user_trigger
from quellgeist.agent.providers import Provider
from quellgeist.agent.schema import Diagnosis

# The abstention reasons the LOOP synthesizes (initial placeholder;
# step-budget exhaustion), as opposed to a model-emitted abstained diagnose.
# Downstream scorers must tell the two apart -- the abstention probe and the
# comparison matrix count only DELIBERATE abstention as abstaining (DR-0020
# decision 6) -- so the prefixes are a public contract, not string coincidence.
_FALLBACK_INITIAL = "loop did not run"
_FALLBACK_EXHAUSTED_PREFIX = "no valid diagnosis within"
FALLBACK_ABSTENTION_PREFIXES = (_FALLBACK_EXHAUSTED_PREFIX, _FALLBACK_INITIAL)


@dataclass
class ToolSpec:
    name: str
    description: str  # shown to the model in the system prompt
    fn: Callable[..., list[dict[str, Any]]]  # returns rows (log rows / commits)


@dataclass
class LoopResult:
    diagnosis: Diagnosis
    steps: int
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    schema_violations: list[str] = field(default_factory=list)
    seen_handles: set[tuple[str, Any]] = field(default_factory=set)
    # The full message transcript exactly as the loop built it (system, trigger,
    # assistant turns, observations, retries — including the final assistant
    # reply). First-class so the DR-0020 trajectory builder's byte-fidelity
    # guarantee rests on a documented contract, not on aliasing loop internals.
    messages: list[dict[str, str]] = field(default_factory=list)

    def cited_handles(self) -> set[tuple[str, Any]]:
        return {ref.key for h in self.diagnosis.hypotheses for ref in h.evidence}

    def cited_but_unseen_handles(self) -> set[tuple[str, Any]]:
        """Wave-1 early-read measurement (DR-0009): handles the model cited that
        no tool returned this run -- a proxy for fabrication. NOT the guarantee;
        the deterministic check against the real signal set, and enforcement,
        land in Wave 2 (fabrication_check.py + verifier)."""
        return self.cited_handles() - self.seen_handles


def _record_seen(result: LoopResult, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if "metric" in row:  # metric series (Wave 3): the series name is the handle
            result.seen_handles.add(("metric", row["metric"]))
        elif "id" in row:  # log row
            result.seen_handles.add(("log", row["id"]))
        if "sha" in row:  # commit
            result.seen_handles.add(("commit", row["sha"]))


def _abstain(reason: str) -> Diagnosis:
    return Diagnosis(abstained=True, abstention_reason=reason, hypotheses=[])


def _retry_msg(error: str) -> str:
    return (
        f"Your previous response was not a valid action: {error}. Respond with "
        "EXACTLY ONE JSON object -- a tool action or a diagnose action -- and "
        "nothing else."
    )


def run_loop(
    provider: Provider,
    tools: list[ToolSpec],
    *,
    now: str,
    max_steps: int = 8,
) -> LoopResult:
    # max_steps=8 is the shared default with the CLI (--max-steps) and the eval
    # harness: room for ~2 tool calls plus a few schema-violation/tool-failure
    # retries before the model must diagnose, while still bounding a stuck loop.
    by_name = {t.name: t for t in tools}
    tool_lines = [f"{t.name}: {t.description}" for t in tools]
    messages: list[dict[str, str]] = [
        {"role": "system", "content": build_system_prompt(tool_lines)},
        {"role": "user", "content": user_trigger(now)},
    ]
    result = LoopResult(diagnosis=_abstain(_FALLBACK_INITIAL), steps=0)
    result.messages = messages  # the loop appends in place; the reference is live

    for step in range(1, max_steps + 1):
        result.steps = step
        text = provider.complete(messages)
        messages.append({"role": "assistant", "content": text})

        try:
            obj = _extract_json(text)
        except _ParseError as e:
            result.schema_violations.append(str(e))
            messages.append({"role": "user", "content": _retry_msg(str(e))})
            continue

        action = obj.get("action")

        if action == "diagnose":
            try:
                result.diagnosis = Diagnosis(**obj.get("diagnosis", {}))
                return result
            except (ValidationError, TypeError) as e:
                result.schema_violations.append(str(e))
                messages.append({"role": "user", "content": _retry_msg(str(e))})
                continue

        if action in by_name:
            args = obj.get("args")
            if not isinstance(args, dict):
                msg = f"'args' for {action!r} must be a JSON object"
                result.schema_violations.append(msg)
                messages.append({"role": "user", "content": _retry_msg(msg)})
                continue
            result.tool_calls.append((action, args))
            try:
                rows = by_name[action].fn(**args)
            except Exception as e:  # tool failed -> observe + retry, never crash
                msg = f"tool {action} failed: {type(e).__name__}: {e}"
                result.schema_violations.append(msg)
                messages.append({"role": "user", "content": _retry_msg(msg)})
                continue
            _record_seen(result, rows)
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation from {action}: {json.dumps(rows)}",
                }
            )
            continue

        msg = f"unknown action {action!r}; valid: {sorted(by_name)} or 'diagnose'"
        result.schema_violations.append(msg)
        messages.append({"role": "user", "content": _retry_msg(msg)})

    # exhausted without a valid diagnosis -> graceful abstention, never crash
    result.diagnosis = _abstain(
        f"{_FALLBACK_EXHAUSTED_PREFIX} {max_steps} steps "
        f"({len(result.schema_violations)} schema violation(s))"
    )
    return result
