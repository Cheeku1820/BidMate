"""eval/rubric.py's grade() response-validation -- the parts that don't
need a live API call. eval/ is offline tooling with real API calls in
its main path (see eval/README.md); this test exercises only the
deterministic validation around that call, using a mocked Anthropic
client."""

from unittest.mock import MagicMock, patch

import pytest

from eval.rubric import grade
from eval.warning_eval_cases import CASES


def test_eval_cases_are_well_formed():
    for case in CASES:
        assert case["id"]
        assert case["tags"]
        for t in case["tags"]:
            assert "tag" in t and "count" in t


def _fake_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    msg = MagicMock()
    msg.content = [block]
    return msg


def test_grade_rejects_an_invalid_criterion_score():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        '{"specificity": "pass", "faithfulness": "maybe", "actionability": "pass", "consequence_realism": "pass", "notes": ""}'
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        with pytest.raises(ValueError, match="faithfulness"):
            grade([{"tag": "F2", "count": 3}], "", {"title": "x", "found": "y", "why": "z", "fix": "w", "where": "v"})


def test_grade_parses_a_well_formed_response():
    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_response(
        '{"specificity": "pass", "faithfulness": "fail", "actionability": "pass", "consequence_realism": "pass", "notes": "cites a sheet not in the input"}'
    )
    with patch("anthropic.Anthropic", return_value=fake_client):
        result = grade([{"tag": "F2", "count": 3}], "", {"title": "x", "found": "y", "why": "z", "fix": "w", "where": "v"})
    assert result["faithfulness"] == "fail"
