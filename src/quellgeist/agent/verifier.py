"""Verifier pass (Wave 2 -- STUB; logic deferred, see DR-0014).

The planned second reliability layer (DR-0003, DR-0009): a stronger model
confirms the cited evidence SUPPORTS each hypothesis and forces abstention
otherwise. The LOGIC is deliberately deferred -- writing the prompt/parse against
an assumed model before the real reasoner's citation behaviour is measured would
bake in untested assumptions. Build it after (a) the DR-0012 verifier-model
decision and (b) the Qwen3-4B id-fidelity run. Only the model-agnostic config
knob is wired now.

TODO(Wave 2, after the Qwen id-fidelity run + DR-0012):
  - implement ``verify``: resolve each cited handle to its signal row, ask the
    verifier whether the evidence supports the cause, drop unsupported
    hypotheses, and force a graceful abstention if none survive;
  - keep it conservative (abstain over confirm) and JSON-action (no native
    function-calling), like the loop (DR-0010);
  - the diagnosis judged / fabrication-checked downstream is the VERIFIED one.
"""

from __future__ import annotations

import os
from typing import Any

from quellgeist.agent.providers import DEFAULT_MODEL, LiteLLMProvider, Provider
from quellgeist.agent.schema import Diagnosis


def default_verifier_provider() -> Provider:
    """Config knob (wired now): build the verifier provider from
    ``QG_VERIFIER_MODEL`` (falls back to ``QG_MODEL``). Intended to be a stronger
    model than the reasoner. The verifier LOGIC is not implemented yet."""
    return LiteLLMProvider(model=os.environ.get("QG_VERIFIER_MODEL", DEFAULT_MODEL))


def verify(
    diagnosis: Diagnosis,
    logs: list[dict[str, Any]],
    commits: list[dict[str, Any]],
    provider: Provider,
) -> Diagnosis:
    """Confirm cited evidence supports each hypothesis; abstain otherwise.

    NOT IMPLEMENTED -- deferred until the DR-0012 verifier-model decision and the
    Qwen3-4B id-fidelity run (DR-0014). See the module docstring."""
    raise NotImplementedError(
        "verifier pass lands after the DR-0012 decision + the Qwen id-fidelity run"
    )
