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


def test_skips_a_stray_brace_in_the_preamble():
    # A chatty local model may put a brace in its prose before the real action;
    # decoding only from the FIRST brace would fail, so scan forward.
    assert extract_json('Based on logs {id 2} => {"action": "diagnose"}') == {
        "action": "diagnose"
    }


def test_skips_non_object_json_before_the_object():
    assert extract_json('prefix {not json} then {"ok": 1}') == {"ok": 1}


def test_all_braces_invalid_raises():
    with pytest.raises(JSONActionError, match="invalid JSON"):
        extract_json("here {is not} valid {json either}")
