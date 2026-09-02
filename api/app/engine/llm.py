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

import base64
import json
import os

MODEL = "claude-opus-5"


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].removeprefix("json").strip()
    return json.loads(text)


_VISION_PROMPT = """This is an electrical construction drawing sheet ({number}). Look at the drawing itself and identify the Division 26 electrical devices and fixtures shown on it (receptacles, switches, lighting fixtures/luminaires by type, junction boxes, panels, disconnects, data/telecom outlets, exit/emergency lighting, etc.).

Return ONLY JSON:
{{"summary": "<one sentence on what this sheet shows>",
  "devices": [{{"name": "<device or fixture type>", "count": <approximate integer you can see>, "confidence": "high|medium|low"}}]}}

Approximate counts are fine. Only include electrical devices actually visible on this drawing. If it is a schedule or legend sheet rather than a plan, summarize what it defines and list the item types it names."""


def read_sheet_image(png_bytes: bytes, sheet_number: str) -> dict:
    """Claude reads one rendered drawing sheet (vision) and reports the
    electrical devices it sees. Returns {} on any failure, so the vision
    pass is purely additive -- the deterministic takeoff never depends on
    it. Extracted image content is treated as data, never instruction."""
    if not available():
        return {}
    from anthropic import Anthropic

    try:
        client = Anthropic()
        msg = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.standard_b64encode(png_bytes).decode(),
                            },
                        },
                        {"type": "text", "text": _VISION_PROMPT.format(number=sheet_number or "electrical sheet")},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _parse_json(text)
    except Exception:  # noqa: BLE001 -- vision is best-effort enrichment
        return {}


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
      "confidence": "<high|medium|low>",
      "warning": <null if confidence is "high", otherwise an object: {{"title": "<short label, e.g. 'Fixture type needs confirmation'>", "found": "<what you actually found for THIS tag, citing its real count and sheet(s) from the tags/schedule text above>", "why": "<the real consequence of not resolving this, specific to this item>", "fix": "<the concrete next step an estimator should take>", "where": "<only sheet numbers that appear in the tags or schedule text above>"}}>
    }}
  ]
}}

Rules:
- Include every tag. If a tag is clearly not a device (a note, a grid label, a panel-schedule header like VA/CKT/AMP), set system "Unknown", category "Unclassified", material_cost 0, labor_hours 0, confidence "low".
- Confidence "high" for standard, unambiguous devices whose tag maps cleanly to one catalog item — receptacles, switches, junction boxes, data/telecom outlets, disconnects. These are counted the same way regardless of schedule.
- Confidence "medium" for fixture-type letters (A-H): count them as luminaires, name them from the schedule when the text supports it, else "Luminaire type X" — the exact fixture still needs a person to confirm against the luminaire schedule.
- Confidence "low" only for genuinely unrecognized or non-device tags.
- When you set "warning" (any item below "high" confidence), ground every field only in the tag counts and schedule text given above. Never state a sheet number, schedule entry, or fact that was not provided to you.
- Write "warning" text the way a knowledgeable electrical estimator would explain it to a colleague: sentence case, plain construction language, no mention of models, confidence scores, or "I think" -- state it as a fact about the drawing, not a hedge about your own certainty.
- "warning" is null when confidence is "high" -- a device the schedule and tags already confirm needs no explanation.
- Do not include markup, overhead, profit, or tax. Material and labor only."""


def estimate(tags: list[dict], schedule_text: str, location: str) -> dict:
    """Returns {location_labor_rate, material_factor, location_note, items:[...]}.
    Each item below "high" confidence also carries a "warning" object --
    the model's own grounded four-field explanation, written in this same
    call rather than synthesized afterward (grounded-classification-
    warnings-design.md). Raises if the API key is missing or the
    call/parse fails -- the caller handles the fallback."""
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
