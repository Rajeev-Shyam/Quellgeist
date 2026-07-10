"""Operator hint injection around the frozen loop (Wave 8, T8.3; DR-0023 HITL).

The webhook (or a steer decision) may carry an operator ``hint``. We surface it to the
model as ONE extra operator message, added **around** the frozen loop — never by editing
``agent/loop.py`` or any frozen string (F4/F6). The mechanism is a thin provider wrapper:
on the loop's FIRST ``complete`` call (right after the frozen system prompt + trigger),
it appends a single ``Operator hint: …`` user turn to the live message list, then delegates
to the wrapped provider. Subsequent calls pass straight through.

Because the hint is opt-in (only when an operator supplies one) and lives entirely in this
new module, the measured train/serve path — which never passes a hint — is byte-identical
to before, so the fine-tune's frozen surface is untouched. Between-steps injection (a note
after each observation) is intentionally NOT done here: it would require re-driving the loop
and risk touching the frozen ``Observation from …`` format (spec §HITL, "stretch").
"""

from __future__ import annotations

from quellgeist.agent.providers import Provider


class HintProvider:
    """Wrap a provider so the operator hint appears as one extra message on the first
    ``complete`` call. Delegates every other attribute (``calls`` for usage capture, etc.)
    to the wrapped provider, so cost/observability are unchanged."""

    def __init__(self, base: Provider, hint: str) -> None:
        self._base = base
        self._hint = hint
        self._injected = False

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self._injected:
            # Append (not insert) so the hint follows the frozen system+trigger turns; the
            # loop holds `messages` live and records it in the trace, so the note is audited.
            messages.append({"role": "user", "content": f"Operator hint: {self._hint}"})
            self._injected = True
        return self._base.complete(messages)

    def __getattr__(self, name: str):
        # Delegate everything else (notably `calls`, read by summarize_usage) to the base.
        return getattr(self._base, name)
