"""LLM estimator (Claude): classifies the counted device tags into catalog
items and prices them for the project's location in one call.

This is the "language reads" half, done directly with the model rather than
a formal agent (the demo build's simplification). It takes the deterministic
counts (tags + counts + the sheet's schedule text) and the location, and
returns, per tag: a Division 26 catalog name, unit, national material cost,
NECA labor hours, and a confidence -- plus a location-adjusted labor rate
and material factor. The engine multiplies; the model never sees or sets a
total.

Requires ANTHROPIC_API_KEY. Callers fall back to the deterministic
classifier + a regional table when this raises, so a missing key or a
transient error never breaks the estimate.
"""

from __future__ import annotations

import json
import os

MODEL = "claude-opus-5"


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _prompt(tags: list[dict], schedule_text: str, location: str) -> str:
    tag_lines = "\n".join(f"- {t['tag']}: appears {t['count']} time(s)" for t in tags)
    schedule = (schedule_text or "").strip()[:6000]
    return f"""You are an electrical estimator's assistant helping price a Division 26 takeoff.

Project location: {location or "United States (national average)"}

These device tags were counted on the electrical drawings (deterministically, from the drawing text). Classify each tag into a standard Division 26 electrical catalog item, and give typical costs. Use the schedule/legend text below to interpret fixture-type letters when possible.

Tags counted:
{tag_lines}

Schedule / legend text extracted from the sheets (may be partial):
\"\"\"
{schedule or "(none extracted)"}
\"\"\"

Return ONLY a JSON object, no prose, of this exact shape:
{{
  "location_labor_rate": <number, loaded electrician $/hr for this location>,
  "material_factor": <number, local material cost vs national average, e.g. 1.0 = national, 1.35 = high-cost remote area>,
  "location_note": "<one short sentence on the local cost basis>",
  "items": [
    {{
      "tag": "<the tag>",
      "name": "<catalog item name, e.g. '2x4 LED troffer', '20A duplex receptacle'>",
      "system": "<Lighting|Power|Distribution|Low voltage|Life safety|Unknown>",
      "category": "<Fixtures|Devices|Boxes|Equipment|Unclassified>",
      "unit": "ea",
      "material_cost": <number, national material $ per unit>,
      "labor_hours": <number, NECA-style install labor hours per unit>,
      "confidence": "<high|medium|low>"
    }}
  ]
}}

Rules:
- Include every tag. If a tag is clearly not a device (a note, a grid label, a panel-schedule header like VA/CKT/AMP), set system "Unknown", category "Unclassified", material_cost 0, labor_hours 0, confidence "low".
- Confidence "high" for standard, unambiguous devices whose tag maps cleanly to one catalog item — receptacles, switches, junction boxes, data/telecom outlets, disconnects. These are counted the same way regardless of schedule.
- Confidence "medium" for fixture-type letters (A-H): count them as luminaires, name them from the schedule when the text supports it, else "Luminaire type X" — the exact fixture still needs a person to confirm against the luminaire schedule.
- Confidence "low" only for genuinely unrecognized or non-device tags.
- Do not include markup, overhead, profit, or tax. Material and labor only."""


def estimate(tags: list[dict], schedule_text: str, location: str) -> dict:
    """Returns {location_labor_rate, material_factor, location_note, items:[...]}.
    Raises if the API key is missing or the call/parse fails -- the caller
    handles the fallback."""
    from anthropic import Anthropic  # imported lazily so the module loads without the SDK

    client = Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        output_config={"effort": "low"},  # a structured lookup -- keep it fast for the demo
        messages=[{"role": "user", "content": _prompt(tags, schedule_text, location)}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
    # Tolerate a ```json fence if the model adds one.
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)
