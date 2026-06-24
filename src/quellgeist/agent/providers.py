"""Model-agnostic provider layer (Wave 1, Task 6).

A thin wrapper over LiteLLM so the reasoner is swappable by config: Gemini's free
tier while iterating in Codespaces (no local model, no paid API), local Qwen3-4B
via Ollama at home / Colab in Wave 4 -- a one-line config change (DR-0002,
DR-0008).

The loop talks only to ``Provider.complete(messages) -> str`` -- plain chat
completion, text in, text out. The agent loop is a model-agnostic JSON-action
ReAct loop (it parses tool actions from the model's text), so we deliberately do
NOT depend on any backend's native function-calling, whose support and quality
vary across Gemini vs a 4-bit Qwen on Ollama. This keeps the loop identical on
every backend -- the property Wave 0 relied on.

``complete`` retries transient provider failures (503 overload, 429 rate limit,
500s, timeouts) with bounded, jittered exponential backoff, and passes an
explicit per-call ``timeout`` so a hung request can't silently wedge the loop.
This is explicit and tested rather than delegated to LiteLLM's opaque
``num_retries`` because the project's headline is *provable* reliability: a
single transient 503 must not abort a diagnosis, and in Wave 2 it must not
redden a 50-scenario CI run -- the jitter keeps a batch of scenarios all hitting
the same 503 from resynchronising their retries into a thundering herd. Retry
does NOT rescue a hard ``limit: 0`` quota (that needs account validation), only
genuinely transient failures.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

DEFAULT_MODEL = os.environ.get("QG_MODEL", "gemini/gemini-2.0-flash")


@runtime_checkable
class Provider(Protocol):
    """Anything the loop can reason with: messages in, assistant text out."""

    def complete(self, messages: list[dict[str, str]]) -> str: ...


class LiteLLMProvider:
    """Provider backed by LiteLLM. ``litellm`` is imported lazily inside
    ``complete`` so importing this module (and the loop, and its mocked tests)
    needs no provider package and no API key -- only a real call does.
    Temperature defaults to 0.0 for deterministic decoding (reliability project;
    matches Wave 0). Note: Gemini-3.x warns that temperature < 1.0 may degrade
    its reasoning, but the real default reasoner is Qwen3-4B where we control
    sampling fully -- Gemini here is only the Codespaces convenience model."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        timeout: float = 60.0,
    ) -> None:
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout  # per-call ceiling; a hung request raises Timeout

    def complete(self, messages: list[dict[str, str]]) -> str:
        import random
        import time

        import litellm
        from litellm.exceptions import (
            InternalServerError,
            RateLimitError,
            ServiceUnavailableError,
            Timeout,
        )

        retryable = (
            ServiceUnavailableError,
            RateLimitError,
            InternalServerError,
            Timeout,
        )
        delay = self.backoff_base
        for attempt in range(self.max_retries):
            try:
                resp = litellm.completion(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    timeout=self.timeout,
                )
                return resp.choices[0].message.content or ""
            except retryable:
                if attempt == self.max_retries - 1:
                    raise  # exhausted: surface the real provider error + traceback
                # full jitter over [delay, 2*delay): decorrelates concurrent
                # scenarios' retries so they don't stampede the provider in sync.
                time.sleep(delay + random.uniform(0.0, delay))
                delay *= 2  # exponential backoff
        raise RuntimeError("unreachable: retry loop exited without return or raise")
