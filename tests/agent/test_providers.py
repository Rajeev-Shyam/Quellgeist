"""Tests for the provider layer's retry/backoff (Wave 1, Task 6)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import litellm
import pytest
from litellm.exceptions import BadRequestError, ServiceUnavailableError

from quellgeist.agent.providers import LiteLLMProvider


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
