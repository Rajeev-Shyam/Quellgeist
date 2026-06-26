"""Shared JSON-action parsing (Wave 2).

The loop, the verifier, and the LLM-judge all use the same convention: the model
replies with EXACTLY ONE JSON object as text (no native function-calling, so the
behaviour is identical on Gemini and a local 4-bit Qwen -- DR-0008/DR-0010). This
module is the one place that turns that text into a dict, tolerant of a model that
wraps the object in prose or a ```json fence.
"""

from __future__ import annotations

import json
from typing import Any


class JSONActionError(ValueError):
    """The model output did not contain a single parseable JSON object."""


def extract_json(text: str) -> dict[str, Any]:
    """Return the first top-level JSON object in ``text``.

    Finds the first ``{`` and decodes from there, so a model that emits a short
    preamble or a code fence before the object still parses. Raises
    ``JSONActionError`` if there is no object or it is malformed."""
    start = text.find("{")
    if start == -1:
        raise JSONActionError("no JSON object found in model output")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError as e:
        raise JSONActionError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise JSONActionError("the JSON action must be an object")
    return obj
