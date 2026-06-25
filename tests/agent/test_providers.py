"""Tests for the provider layer's retry/backoff (Wave 1, Task 6)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import litellm
import pytest
from litellm.exceptions import (
    BadRequestError,
    RateLimitError,
    ServiceUnavailableError,
)

from quellgeist.agent.providers import LiteLLMProvider, is_provider_unavailable


def _ok(text="ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


def _overloaded():
    return ServiceUnavailableError(
        message="high demand", llm_provider="gemini", model="m"
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(
        time, "sleep", lambda *_: None
    )  # don't actually back off in tests


def test_retries_transient_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:  # fail twice, succeed on the 3rd
            raise _overloaded()
        return _ok("diagnosed")

    monkeypatch.setattr(litellm, "completion", fake)
    out = LiteLLMProvider(model="gemini/x", max_retries=4).complete(
        [{"role": "user", "content": "hi"}]
    )
    assert out == "diagnosed"
    assert calls["n"] == 3


def test_exhausts_retries_then_reraises(monkeypatch):
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        raise _overloaded()

    monkeypatch.setattr(litellm, "completion", fake)
    with pytest.raises(ServiceUnavailableError):
        LiteLLMProvider(model="gemini/x", max_retries=3).complete(
            [{"role": "user", "content": "hi"}]
        )
    assert calls["n"] == 3  # tried exactly max_retries times


def test_non_retryable_propagates_immediately(monkeypatch):
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        raise BadRequestError(message="bad", llm_provider="gemini", model="m")

    monkeypatch.setattr(litellm, "completion", fake)
    with pytest.raises(BadRequestError):
        LiteLLMProvider(model="gemini/x", max_retries=4).complete(
            [{"role": "user", "content": "hi"}]
        )
    assert calls["n"] == 1  # not retried


def test_completion_receives_explicit_timeout(monkeypatch):
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _ok()

    monkeypatch.setattr(litellm, "completion", fake)
    LiteLLMProvider(model="gemini/x", timeout=12.5).complete(
        [{"role": "user", "content": "hi"}]
    )
    assert captured["timeout"] == 12.5  # a hung request can't wedge the loop
    assert captured["model"] == "gemini/x"


def test_backoff_is_jittered_within_bounds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def fake(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:  # fail twice, then succeed
            raise _overloaded()
        return _ok()

    monkeypatch.setattr(litellm, "completion", fake)
    LiteLLMProvider(model="gemini/x", max_retries=4, backoff_base=2.0).complete(
        [{"role": "user", "content": "hi"}]
    )
    # two backoffs: each is base*2^i plus jitter in [0, base*2^i], so the sleep
    # lands in [base*2^i, 2*base*2^i) -- monotone bands, never a fixed value.
    assert len(sleeps) == 2
    assert 2.0 <= sleeps[0] < 4.0
    assert 4.0 <= sleeps[1] < 8.0


def test_is_provider_unavailable_true_for_quota_and_overload():
    # A walled free tier (429) and an overloaded backend (503) are "can't reach
    # the model" -> a SKIP for callers, not a reliability failure (DR-0012).
    assert is_provider_unavailable(
        RateLimitError(message="quota", llm_provider="gemini", model="m")
    )
    assert is_provider_unavailable(
        ServiceUnavailableError(message="busy", llm_provider="gemini", model="m")
    )


def test_is_provider_unavailable_false_for_real_errors():
    # A bad request (the model ran and rejected the input) and a plain bug are
    # NOT availability problems -- they must still surface, never be masked.
    assert not is_provider_unavailable(
        BadRequestError(message="bad", llm_provider="gemini", model="m")
    )
    assert not is_provider_unavailable(ValueError("a real bug"))
