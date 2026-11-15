"""Labor and material assumptions, read off the resolvers' own bases.

docs/specs/rom-estimate.md. Nothing here recomputes a price or an hour.
`app.takeoff.pricing` already resolves every line through the firm's
precedence chain and reports which tier won; this module's whole job is
to translate that signal into the basis vocabulary and say so in words a
GC can read. Recomputing would mean two pricing implementations that
drift, and the drift would show up as a document whose disclosures
describe a different number than the one printed on it.

**Where the counted/assumed line falls.** A number is *counted* when it
came from this job: a supplier's quote for this item, a price an
estimator typed, a market lookup for this item in this ZIP on a date.
It is *assumed* when it was derived from somewhere other than this job
-- the firm's tables, what gear of a class costs, a rule.

That puts a market estimate on the counted side while it still widens
the budget range, which is not a contradiction: the origin tag answers
"did somebody have to invent this number", and the basis spread answers
"how firm is the method". A catalog price for the right item on a known
date is a real price that is nonetheless not contractor net pricing.
Hence two outputs from the same walk -- `*_assumptions` for what gets
disclosed, `cost_exposures` for what widens the range.

Grouping is deliberate and not uniform. Firm-table bases are grouped
into one line naming the count, because forty identical disclosures is a
page nobody reads. A class average is named per item, because "which
piece of gear is carrying a price nobody quoted" is exactly the question
a GC asks, and collapsing it would answer the opposite one.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app.estimate import copy
from app.estimate.range import Exposure
from app.takeoff.models import Item, Project, Sheet
from app.takeoff.totals import ResolvedLine, resolved_lines

# The resolvers' own source labels, mapped to the basis vocabulary.
# `None` means the number came from this job and nothing was assumed, so
# no assumption is written -- an empty disclosure is worse than none,
# because a reader counts the lines.
MATERIAL_BASIS: dict[str | None, str | None] = {
    "Supplier quote": "supplier_quote",
    "Project price": None,      # an estimator typed it for this job
    "Allowance": None,          # an estimator decided it for this job
    "Company price": "firm_default",
    "Market estimate": "market_estimate",
    "Regional baseline": "class_average",
    None: None,                 # nothing priced it; the line is unpriced
}

LABOR_BASIS: dict[str | None, str | None] = {
    "Estimator entered": None,
    "Company standard": "firm_default",
    "Company crew rate": "firm_default",
    "Estimated basis": "class_average",
    None: None,
}

# Bases that get one grouped line naming the count rather than one line
# per item.
_GROUPED = ("firm_default", "class_average")




def _grouped_line(template: dict, *, section: str, basis: str, items: list[Item],
                  kind: str, value: str | None = None, unit: str | None = None) -> dict:
    """One assumption standing for every item that shares a basis.

    The count goes in `found` rather than being left for the reader to
    infer: "forty-two receptacles" and "one receptacle" are different
    disclosures, and a line that does not say which is a line that
    cannot be checked.

    `kind` goes into `subject_ref` so two disclosures in one section can
    never collide on identity. The firm-table and derived hours
    disclosures share the title "Installation hours" on purpose -- it is
    the right words for both -- so the title alone is not an identity,
    and `write.regenerate`'s dedup keys off the full subject.
    """
    return {
        "section": section,
        "subject_kind": "project",
        "subject_ref": f"{section}:{kind}",
        "basis": basis,
        "title": template["title"],
        "found": template["found"].format(items=copy.plural(len(items), "line")),
        "why": template["why"],
        "where": template["where"],
        "value": value,
        "unit": unit,
        "source": "engine",
    }


def labor_assumptions(db: DbSession, project: Project, *,
                      exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """The hours and the rate, each disclosed once if it was assumed.

    Two lines at most, by design. Every labor dollar on the document is
    hours times a rate, so those are the two numbers a reader needs to
    interrogate; a per-item breakdown would bury both.
    """
    hours_groups: dict[str, list[Item]] = {}
    rate_groups: dict[str, list[Item]] = {}
    for line in resolved_lines(db, project, exclude=exclude):
        # A line whose labor did not resolve assumed nothing -- there is
        # no number to disclose, and the ROM renders it as not priced.
        if line.labor_rate_basis is None and line.labor_hours_basis is None:
            continue
        hours_basis = LABOR_BASIS.get(line.labor_hours_basis)
        if hours_basis:
            hours_groups.setdefault(hours_basis, []).append(line.item)
        rate_basis = LABOR_BASIS.get(line.labor_rate_basis)
        if rate_basis:
            rate_groups.setdefault(rate_basis, []).append(line.item)

    rows = []
    for basis, items in sorted(hours_groups.items()):
        template = copy.FIRM_HOURS if basis == "firm_default" else copy.ESTIMATED_HOURS
        rows.append(_grouped_line(template, section="labor", basis=basis, items=items,
                                  kind="hours"))
    for basis, items in sorted(rate_groups.items()):
        template = copy.FIRM_RATE if basis == "firm_default" else copy.ESTIMATED_RATE
        rows.append(_grouped_line(template, section="labor", basis=basis, items=items,
                                  kind="rate"))
    return rows


def material_assumptions(db: DbSession, project: Project, *,
                         exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """Prices that did not come from this job.

    Firm-price-list lines are grouped; class averages are named one by
    one. See the module docstring for why the grouping is not uniform.
    """
    firm_priced: list[Item] = []
    rows = []
    for line in resolved_lines(db, project, exclude=exclude):
        item = line.item
        basis = MATERIAL_BASIS.get(line.material_basis)
        if basis == "firm_default":
            firm_priced.append(item)
        elif basis == "class_average":
            rows.append({
                "section": "material",
                "subject_kind": "item",
                "subject_id": item.id,
                "basis": "class_average",
                "title": copy.CLASS_AVERAGE["title"].format(name=item.name),
                "found": copy.CLASS_AVERAGE["found"],
                "why": copy.CLASS_AVERAGE["why"],
                # Names the sheet the gear was counted on, not just the
                # screen: a GC asking "which switchboard" needs the
                # drawing, and a disclosure that cannot be traced to one
                # is a disclosure that cannot be checked.
                "where": copy.CLASS_AVERAGE["where"].format(
                    name=item.name, sheet=_sheet_number(db, item)),
                # The RESOLVED price, not the engine's stored column --
                # the document must disclose the number it printed.
                "value": copy.dollars(line.material_cost) or None,
                "source": "engine",
            })

    if firm_priced:
        rows.insert(0, _grouped_line(copy.FIRM_PRICE, section="material",
                                     basis="firm_default", items=firm_priced, kind="price"))
    return rows


def _sheet_number(db: DbSession, item: Item) -> str:
    sheet = db.get(Sheet, item.sheet_id)
    return sheet.number if sheet is not None else ""


def cost_exposures(db: DbSession, project: Project, *,
                   exclude: set[uuid.UUID] | None = None) -> list[Exposure]:
    """Dollars resting on each basis, for the budget range.

    Separate from the assumption rows on purpose: a market estimate is a
    counted line that still widens the range, and a quoted price is a
    counted line that does not. Collapsing the two outputs into one
    would force a choice between disclosing a quote as an assumption or
    pricing a market estimate as if it were quoted.

    **A labor dollar rests on two bases, and both count.** The hours can
    come from the firm's table (±10%) while the rate was derived (±20%);
    the cost is hours times rate, so it is loose on both counts and the
    spec's linear combination wants both reported. An earlier version
    took the rate basis `or` the hours basis, which silently discarded
    whichever came second and narrowed the range on an assumption nobody
    had checked -- the one direction an error here must never go.

    **An inferred identity widens the range too.** A quoted price for
    the wrong item is not a reliable number, so a line whose name was
    read from context rather than matched to a legend row carries its
    own exposure on top of whatever priced it.
    """
    buckets: dict[str, Decimal] = {}

    def add(basis: str | None, dollars: Decimal) -> None:
        if basis and dollars:
            buckets[basis] = buckets.get(basis, Decimal("0")) + dollars

    for line in resolved_lines(db, project, exclude=exclude):
        add(MATERIAL_BASIS.get(line.material_basis), line.material_cost)
        # Both halves, not one: see the docstring.
        add(LABOR_BASIS.get(line.labor_hours_basis), line.labor_cost)
        add(LABOR_BASIS.get(line.labor_rate_basis), line.labor_cost)
        if line.item.classification_basis == "inferred":
            add("inferred", line.total_cost)

    return [Exposure(basis, dollars) for basis, dollars in sorted(buckets.items()) if dollars > 0]
