"""Robust JSON extraction from LLM responses."""

from __future__ import annotations

import pytest

from app.agents.json_utils import extract_json_object


def test_plain_json():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_json_in_code_fence():
    text = 'Claro, aquí tienes:\n```json\n{"a": 1}\n```\nEspero que sirva.'
    assert extract_json_object(text) == {"a": 1}


def test_nested_json():
    text = 'prefix {"a": {"b": 2}} suffix'
    assert extract_json_object(text) == {"a": {"b": 2}}


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json_object("no hay json aquí")
