"""Takeoff assumptions: the quantities that were derived, not counted.

docs/specs/rom-estimate.md. **Counting is not touched by anything in
this module.** It reads placements out of the file and is tested against
asserted counts, never tuned; a count it produced is counted, full stop.
What this covers is the quantities Counting cannot produce because they
are not in the file for anyone to read:

- **Branch wire and conduit.** The drawing shows a homerun arrow, not a
  route. The run length is judgment from ceiling height and building
  geometry, and `app.engine.assemblies` prices it off the firm's
  feet-per-device rule. ROADMAP 2.1 names wire and conduit the largest
  single threat to a defensible total, which makes this the single most
  important line on the whole document.
- **A length measured against a scale nobody confirmed.** The sheet has
  no scale, or two of them, and every measured item on it rests on a
  choice that was never made.
- **A length measured off the drawing at all**, as opposed to read from
  a written dimension.
- **An item named from context** rather than matched to a legend row
  that defines its symbol (`Item.classification_basis`). The count is
  still counted; what the thing is was read rather than looked up.

What is deliberately NOT produced here: a total footage figure. The
assembly expansion folds wire and conduit into each parent device's
`material_cost` rather than emitting footage rows
(`app/engine/rows.py`), so there is no stored quantity to total, and
deriving one from the rule would mean printing a number traceable to
nothing on a document whose entire premise is that every number is
traceable. The rule itself and the count of lines priced by it are both
true and both checkable; the product of them is not, so it is not
printed. The approved mockup's "6,820 ft" was illustrative.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.estimate import copy
from app.takeoff.models import Item, Project, Sheet
from app.takeoff.totals import countable_items

# A mirror of app.engine.assemblies.FEET_PER_DEVICE, not an import of
# it. `app.engine.assemblies` is banned from the API process
# (tests/test_api_import_boundary.py) because the package it belongs to
# pulls in a PDF parser, and this module is reached from the estimate
# router. The same deliberate small duplication `ingest.py` carries for
# SHEET_KINDS, kept honest the same way:
# test_the_feet_per_device_rule_mirrors_the_engine asserts the two are
# equal, and that test may import the engine because a test is not the
# API process.
FEET_PER_DEVICE = 30.0

# Units that mean a length. A measured item's quantity came off the
# drawing rather than out of a count, which is what makes it depend on
# the sheet's scale.
MEASURED_UNITS = ("ft", "lf", "feet")

# A sheet whose scale is absent, or which carries two labels and so has
# no single scale. Either way the measurements on it rest on a choice
# nobody made; "mixed" is the engine's own word for the second case
# (`Sheet.scale`, and the E2.1 case in README's walkthrough).
_NO_SINGLE_SCALE = ("", "mixed", "unknown", "none")


def _is_measured(item: Item) -> bool:
    return bool(item.path) or (item.unit or "").strip().lower() in MEASURED_UNITS


def takeoff_assumptions(db: DbSession, project: Project, *,
                        exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """Every derived-quantity disclosure for one project.

    Grouping follows the shape of the thing being disclosed rather than
    one rule for everything: the feet-per-device rule is one project-wide
    fact, so it is one line naming how many lines it priced. A missing
    scale is a property of a sheet, so it is one line per sheet -- forty
    measured items on an unscaled sheet is one problem with one fix
    (set the scale), and forty identical disclosures would describe it
    as forty.
    """
    items = [i for i in db.scalars(countable_items(project.id))
             if not (exclude and i.id in exclude)]
    if not items:
        return []

    rows: list[dict] = []

    # 1. Branch wire and conduit, from the firm's rule.
    priced = [i for i in items if i.material_cost and i.material_cost > 0]
    if priced:
        rows.append({
            "section": "takeoff",
            "subject_kind": "project",
            "basis": "rule_of_thumb",
            "title": copy.BRANCH_WIRE["title"],
            "found": copy.BRANCH_WIRE["found"].format(
                lines=copy.plural(len(priced), "line"), feet=_feet()),
            "why": copy.BRANCH_WIRE["why"],
            "where": copy.BRANCH_WIRE["where"],
            "value": _feet(),
            "unit": "ft per device",
            "source": "engine",
        })

    # 2. Items the classifier named from context rather than matched.
    inferred = [i for i in items if i.classification_basis == "inferred"]
    if inferred:
        rows.append({
            "section": "takeoff",
            "subject_kind": "project",
            "basis": "inferred",
            "title": copy.INFERRED_NAMES["title"],
            "found": copy.INFERRED_NAMES["found"].format(
                items=copy.plural(len(inferred), "counted line")),
            "why": copy.INFERRED_NAMES["why"],
            "where": copy.INFERRED_NAMES["where"],
            "source": "engine",
        })

    # 3. A sheet with no single scale, carrying measured items.
    measured = [i for i in items if _is_measured(i)]
    if measured:
        by_sheet: dict[uuid.UUID, list[Item]] = {}
        for item in measured:
            by_sheet.setdefault(item.sheet_id, []).append(item)
        sheets = {
            s.id: s for s in db.scalars(
                select(Sheet).where(Sheet.id.in_(by_sheet.keys()))
            )
        }
        for sheet_id, affected in sorted(by_sheet.items(), key=lambda kv: sheets[kv[0]].number):
            sheet = sheets[sheet_id]
            if (sheet.scale or "").strip().lower() not in _NO_SINGLE_SCALE:
                continue
            rows.append({
                "section": "takeoff",
                "subject_kind": "sheet",
                "subject_id": sheet.id,
                "basis": "scaled",
                "title": copy.MISSING_SCALE["title"].format(sheet=sheet.number),
                "found": copy.MISSING_SCALE["found"].format(
                    sheet=sheet.number, items=copy.plural(len(affected), "measured line")),
                "why": copy.MISSING_SCALE["why"],
                "where": copy.MISSING_SCALE["where"].format(sheet=sheet.number),
                "source": "engine",
            })

        # 4. Every measured length, scaled rather than dimensioned.
        rows.append({
            "section": "takeoff",
            "subject_kind": "project",
            "basis": "scaled",
            "title": copy.SCALED_LENGTHS["title"],
            "found": copy.SCALED_LENGTHS["found"].format(
                items=copy.plural(len(measured), "measured line")),
            "why": copy.SCALED_LENGTHS["why"],
            "where": copy.SCALED_LENGTHS["where"],
            "source": "engine",
        })

    return rows


def _feet() -> str:
    """The rule as the document prints it -- "30" rather than "30.0"."""
    whole = Decimal(str(FEET_PER_DEVICE)).normalize()
    return f"{whole:f}"
