"""Observability: usage summary, correlation binding, log tagging (Wave 7, T7.2)."""

from __future__ import annotations

import structlog

from quellgeist.agent.providers import CallUsage
from quellgeist.observability import (
    configure_logging,
    current_ids,
    get_logger,
    new_run_id,
    run_context,
    summarize_usage,
)


class _Provider:
    def __init__(self, calls):
        self.calls = calls


def test_summarize_usage_sums_tokens_and_latency():
    p = _Provider(
        [
            CallUsage(prompt_tokens=100, completion_tokens=20, latency_s=1.0),
            CallUsage(prompt_tokens=50, completion_tokens=10, latency_s=0.5),
        ]
    )
    s = summarize_usage(p)
    assert s.calls == 2
    assert s.prompt_tokens == 150 and s.completion_tokens == 30
    assert s.latency_s == 1.5


def test_summarize_usage_handles_missing_tokens():
    p = _Provider(
        [CallUsage(prompt_tokens=None, completion_tokens=None, latency_s=2.0)]
    )
    s = summarize_usage(p)
    assert s.calls == 1 and s.prompt_tokens is None and s.completion_tokens is None
    assert s.latency_s == 2.0


def test_summarize_usage_empty():
    s = summarize_usage(_Provider([]))
    assert s == type(s)(
        calls=0, prompt_tokens=None, completion_tokens=None, latency_s=0.0
    )


def test_run_context_binds_and_clears_ids():
    assert current_ids() == {}  # nothing bound outside
    rid = new_run_id()
    with run_context("inc-7", rid):
        assert current_ids() == {"incident_id": "inc-7", "run_id": rid}
    assert current_ids() == {}  # cleared on exit


def test_logs_carry_correlation_ids():
    """A structlog record emitted inside a run_context carries the bound ids via
    merge_contextvars — the correlation contract."""
    captured: list[dict] = []

    def _capture(_logger, _method, event_dict):
        captured.append(dict(event_dict))
        raise structlog.DropEvent

    logger = structlog.wrap_logger(
        None, processors=[structlog.contextvars.merge_contextvars, _capture]
    )
    with run_context("inc-8", "run-8"):
        logger.info("step done", step=2)
    assert captured[-1]["incident_id"] == "inc-8"
    assert captured[-1]["run_id"] == "run-8"
    assert captured[-1]["step"] == 2


def test_configure_logging_is_idempotent():
    configure_logging()
    configure_logging()  # no raise on repeat
    assert get_logger() is not None
