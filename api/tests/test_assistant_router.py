"""app/assistant/router.py and service.py -- the thread and the answer
stream. The model is replaced by a fake everywhere below: these tests
prove what is stored, in what order, and what the wire carries, not
what Claude says."""
import os

from app.assistant import llm


def test_availability_follows_the_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.available() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert llm.available() is True
    assert llm.MODEL == "claude-opus-5"
