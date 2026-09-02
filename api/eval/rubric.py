"""Rubric-based judge for grounded classification warnings
(design doc section D, Layer 2). Scores each generated warning against
independent, atomic criteria rather than one holistic verdict --
decomposed criteria are what keeps an LLM-as-judge's output reliable and
comparable run to run. Not a runtime check: this runs offline, against
the frozen eval set, when the prompt in app/engine/llm.py changes.
"""

from __future__ import annotations

import json

MODEL = "claude-opus-5"

CRITERIA = ("specificity", "faithfulness", "actionability", "consequence_realism")

_JUDGE_PROMPT = """You are grading one warning an electrical-estimating tool generated to explain why an item needs a person's attention.

Input the classifier saw:
Tags counted: {tags}
Schedule/legend text: \"\"\"{schedule_text}\"\"\"

The warning it generated:
Title: {title}
Found: {found}
Why: {why}
Fix: {fix}
Where: {where}

Score each criterion "pass" or "fail":
- specificity: does "found" cite this item's actual tag, count, and sheet, or could this sentence be pasted onto any item unchanged?
- faithfulness: does every claim in the warning trace back to something in the tags or schedule text above? A claim not supported by that input is a fail, even if it sounds plausible.
- actionability: is "fix" a step an estimator could actually go do, or a restatement of the problem dressed up as an instruction?
- consequence_realism: does "why" state a real, item-specific consequence, or generic boilerplate that would fit any warning?

Return ONLY JSON: {{"specificity": "pass"|"fail", "faithfulness": "pass"|"fail", "actionability": "pass"|"fail", "consequence_realism": "pass"|"fail", "notes": "<one sentence on the clearest failure, or \\"\\" if all pass>"}}"""


def grade(tags: list[dict], schedule_text: str, warning: dict) -> dict:
    """One judge call, one warning. Returns a dict with "pass"/"fail"
    per criterion in CRITERIA, plus "notes". Raises on an API failure or
    a response that doesn't parse -- an eval run should surface that
    loudly, not silently skip a case."""
    from anthropic import Anthropic

    client = Anthropic()
    tag_text = ", ".join(f"{t['tag']} x{t['count']}" for t in tags)
    prompt = _JUDGE_PROMPT.format(
        tags=tag_text, schedule_text=(schedule_text or "")[:2000],
        title=warning.get("title", ""), found=warning.get("found", ""),
        why=warning.get("why", ""), fix=warning.get("fix", ""), where=warning.get("where", ""),
    )
    msg = client.messages.create(
        model=MODEL, max_tokens=500, output_config={"effort": "low"},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    result = json.loads(text)
    for c in CRITERIA:
        if result.get(c) not in ("pass", "fail"):
            raise ValueError(f"judge returned an invalid score for {c!r}: {result.get(c)!r}")
    return result
