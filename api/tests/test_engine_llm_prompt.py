"""api/app/engine/llm.py's prompt construction -- pure string building,
no API call, so this is testable without ANTHROPIC_API_KEY."""

from app.engine.llm import _prompt


def test_prompt_asks_for_a_grounded_warning_per_item():
    text = _prompt([{"tag": "F2", "count": 3}], "schedule text here", "Sacramento, CA")
    assert '"warning"' in text
    assert "ground every field only in the tag counts and schedule text given above" in text


def test_prompt_forbids_ai_framing_in_warning_text():
    text = _prompt([{"tag": "F2", "count": 3}], "", "")
    assert "no mention of models, confidence scores" in text


def test_prompt_states_warning_is_null_for_high_confidence():
    text = _prompt([{"tag": "R", "count": 10}], "", "")
    assert '"warning" is null when confidence is "high"' in text
