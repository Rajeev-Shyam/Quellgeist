"""Tests for the verifier stub (Wave 2). Logic deferred -- see DR-0014.

Only the config knob is exercised; the pass itself is a tracked NotImplemented
stub until the DR-0012 decision + the Qwen id-fidelity run.
"""

from __future__ import annotations

import pytest

from quellgeist.agent.schema import Diagnosis
from quellgeist.agent.verifier import default_verifier_provider, verify


def test_verify_is_not_implemented_yet():
    d = Diagnosis(abstained=True, abstention_reason="x", hypotheses=[])
    with pytest.raises(NotImplementedError, match="DR-0012"):
        verify(d, [], [], object())


def test_verifier_model_config_knob_reads_env(monkeypatch):
    monkeypatch.setenv("QG_VERIFIER_MODEL", "gemini/gemini-2.5-pro")
    assert default_verifier_provider().model == "gemini/gemini-2.5-pro"
