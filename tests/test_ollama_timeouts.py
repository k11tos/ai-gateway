"""Timeout compatibility for the retained client module."""
import pytest

import ollama_client as upstream


@pytest.mark.parametrize("value,expected", [("1.5", 1.5), ("oops", 7), ("0", 7), ("-1", 7), ("nan", 7), ("inf", 7)])
def test_timeout_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("OPENROUTER_READ_TIMEOUT", value)
    assert upstream._get_timeout_env("OPENROUTER_READ_TIMEOUT", 7) == expected


def test_timeout_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_READ_TIMEOUT", raising=False)
    assert upstream._get_timeout_env("OPENROUTER_READ_TIMEOUT", 13) == 13
