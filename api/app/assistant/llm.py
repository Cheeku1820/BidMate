"""The one function that calls Claude for the conversation panel.

Kept to a single, argument-complete function so service.py can be
tested with a fake that yields fixed chunks. Adaptive thinking at low
effort: this is chat over a bounded context, not a reasoning task.
Two cached system blocks -- the frozen prompt, then the rendered bundle
-- so a repeat question from the same screen is a cache hit on both.

Requires ANTHROPIC_API_KEY. Without it the route answers 503 before
this module is called; nothing else in the product depends on it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

MODEL = "claude-opus-5"
MAX_TOKENS = 4000


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def stream(system_blocks: list[dict], messages: list[dict]) -> Iterator[str]:
    """Yields text chunks as they arrive. Raises the SDK's typed errors;
    service.py maps them to the wire."""
    from anthropic import Anthropic

    client = Anthropic()
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "low"},
        system=system_blocks,
        messages=messages,
    ) as s:
        yield from s.text_stream
