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

    Scans each ``{`` in order and decodes from there, returning the first that
    yields a JSON object. This tolerates a model that emits a preamble or a code
    fence before the object -- *including* a preamble that itself contains a stray
    ``{`` (e.g. ``Based on the logs {id 2} I conclude: {"action": ...}``), which a
    decode-from-the-first-brace approach would choke on. Raises ``JSONActionError``
    if no ``{`` begins a valid JSON object."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start == -1:
        raise JSONActionError("no JSON object found in model output")
    last_err: json.JSONDecodeError | None = None
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError as e:
            last_err = e  # keep scanning past a non-JSON brace in a preamble
        else:
            if isinstance(obj, dict):
                return obj
        start = text.find("{", start + 1)
    raise JSONActionError(f"invalid JSON: {last_err}")
