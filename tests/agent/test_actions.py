"""Tests for the shared JSON-action parser (Wave 2)."""

from __future__ import annotations

import pytest

from quellgeist.agent.actions import JSONActionError, extract_json


def test_extracts_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extracts_object_after_prose():
    assert extract_json('Sure! {"action": "x"} done') == {"action": "x"}


def test_extracts_from_code_fence():
    assert extract_json('```json\n{"k": true}\n```')["k"] is True


def test_no_object_raises():
    with pytest.raises(JSONActionError, match="no JSON object"):
        extract_json("no braces here")


def test_malformed_object_raises():
    with pytest.raises(JSONActionError, match="invalid JSON"):
        extract_json('{"a": }')
