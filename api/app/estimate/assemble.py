"""The ROM document, assembled from what is already stored.

docs/specs/rom-estimate.md. Reads rather than computes, wherever
something is already computed: `rom_totals` for the arithmetic,
`excluded_item_ids` for what scope removed, the stored `Assumption` rows
for what was assumed. That last one matters -- the rows are read, not
regenerated, which is what lets an estimator's override
(`app.estimate.override`) survive being read back.

**Counted lines are grouped; assumed lines never are.** Every assumption
is listed in full, because listing them is the document's entire
purpose. Counted work is rolled up by system, because a hospital power
plan carries four hundred items and a ROM that prints four hundred rows
is a document nobody reads -- and the section tally still states the
real count.

**What the budget range does and does not cover.** Exposure is computed
from the dollars each basis actually prices (`cost_exposures`), plus the
measured-item dollars that rest on a scale. The feet-per-device rule has
no separable dollars to attach: `app/engine/rows.py` folds branch wire
and conduit into each parent device's `material_cost`, so the only two
options are to widen the range by the parent's whole material cost
(overstating -- most of that figure is the device, not its conduit) or
by nothing. This takes the second, and the limitation is real: the rule
is disclosed on the page and in the qualifications block, where it is
the first line, but it does not widen the range. Separating it needs
footage to be stored as its own quantity, which is a change to the
engine's row shape rather than to this file.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.estimate.basis import BASIS, SECTIONS
from app.estimate.exclusions import excluded_item_ids, excluded_value, excluded_value_by_assumption
from app.estimate.generate_cost import cost_exposures
from app.estimate.generate_takeoff import _is_measured
from app.estimate.range import Exposure, budget_range
from app.estimate.schemas import (
    EstimateLineOut,
    EstimateOut,
    EstimateSectionOut,
    QualificationOut,
    RangeOut,
)
from app.takeoff.models import Assumption, Document, Item, Job, Project, ScopeStatement, Sheet
from app.takeoff.totals import countable_items, resolved_lines, rom_totals

SECTION_LABELS = {
    "scope": "Scope",
    "takeoff": "Takeoff quantities",
    "labor": "Labor",
    "material": "Material",
}

# Scope statements a person has not rejected. Mirrors
# `generate_scope._ADDRESSING_STATUSES` -- the same two statuses count
# as "the documents say this", in both directions.
_LIVE_SCOPE_STATUSES = ("found", "confirmed")

NOTHING_PROCESSED = "No documents have been processed for this project yet, so there is nothing to estimate."
# A project with counted work and no disclosures. Never shown as a
# finished ROM: an assumptions list that is empty because generation has
# not run looks exactly like one that is empty because nothing was
# assumed, and those are opposite claims.
GENERATION_PENDING = (
    "This estimate's assumptions have not been worked out yet. The number below is the takeoff's own "
    "figures and does not yet state what had to be assumed to reach it, so it is not ready to hand over."
)
GENERATION_FAILED = (
    "This estimate's assumptions could not be worked out. The number below does not state what had to be "
    "assumed to reach it, so it is not ready to hand over. Start the takeoff again to rebuild them."
)
NOTHING_READABLE = "No sheet in this set could be read, so nothing was counted."
NOTHING_COUNTED = "The drawings were read but no Division 26 items were counted on them."
EVERYTHING_EXCLUDED = "Every counted line is excluded by the scope assumptions below, so this estimate carries no cost."


def _assumption_line(row: Assumption, removed: Decimal | None) -> EstimateLineOut:
    """One disclosure as a line, tagged with where its number came from.

    `row.origin` is read, not derived. It used to be computed as
    "estimator means counted, engine means assumed", which is right for
    an override -- the moment a derived number stops being derived,
    because somebody went and measured the ceiling -- and wrong for an
    exclusion the scope letter itself stated. That row is written by the
    engine and its number came from the documents, so the spec counts it
    (`counted` includes "a scope statement extracted with a verbatim
    quote"). Deriving it tagged seven quoted fire-alarm rows Assumed.

    Note that origin is not what decides the qualifications block:
    `_qualifications` filters on `source`, because a stated exclusion is
    counted and still moved money, and money that moved is exactly what
    that block exists to name.
    """
    spec = BASIS.get(row.basis)
    return EstimateLineOut(
        id=row.id,
        title=row.title,
        origin=row.origin,
        basis=row.basis,
        basis_label=spec.label if spec else None,
        where=row.where,
        found=row.found,
        why=row.why,
        value=row.value,
        unit=row.unit,
        # An exclusion's amount is the money it removed, shown as what it
        # took out rather than as what it costs. Resolved per exclusion,
        # never stored -- a stored figure would be a number that was true
        # once, and this one has to stay right after an item is rejected
        # or a price changes.
        amount=removed if removed else row.excluded_value,
        source=row.source,
    )


def _scope_counted(db: DbSession, project: Project) -> list[EstimateLineOut]:
    """What the documents themselves said the work is.

    Listed one by one rather than grouped: there are few of them, they
    are the scope, and a reader checking an exclusion needs the sentence
    the document actually carried.
    """
    rows = db.execute(
        select(ScopeStatement, Document.filename)
        .join(Document, Document.id == ScopeStatement.document_id)
        .where(
            ScopeStatement.project_id == project.id,
            ScopeStatement.status.in_(_LIVE_SCOPE_STATUSES),
        )
        .order_by(ScopeStatement.created_at, ScopeStatement.id)
    ).all()
    lines = []
    for statement, filename in rows:
        page = statement.page_index or 1
        lines.append(EstimateLineOut(
            id=statement.id,
            title=statement.edited_text or statement.text,
            origin="counted",
            where=f"{filename}, page {page}",
            found="Stated in the documents.",
        ))
    return lines


def _takeoff_counted(db: DbSession, project: Project, exclude: set[uuid.UUID],
                     unpriced_by_system: dict[str, int],
                     cost_by_system: dict[str, Decimal]) -> list[EstimateLineOut]:
    """Counted work, one line per system.

    Quantity is deliberately absent from the rolled-up line: a system
    mixes units -- 62 fixtures and 185 feet of conduit do not add -- and
    a single number over mixed units would be the kind of arithmetic
    nobody can check. The line count and the dollars are both well
    defined, so those are what it carries.
    """
    query = countable_items(project.id)
    if exclude:
        query = query.where(Item.id.not_in(exclude))
    # Counts come from the database; MONEY comes from `rom_totals`'s
    # resolved figures. A second SUM over `Item.total_cost` here would
    # be the engine's stored guess sitting beside the resolved total and
    # disagreeing with it -- the bug `resolved_lines` exists to close.
    counts = db.execute(
        query.with_only_columns(Item.system, func.count()).group_by(Item.system)
    ).all()
    rows = sorted(
        ((system, count, cost_by_system.get(system, Decimal("0"))) for system, count in counts),
        key=lambda r: (-r[2], r[0]),
    )
    lines = []
    for system, count, cost in rows:
        unpriced = unpriced_by_system.get(system, 0)
        found = f"{count} counted line{'' if count == 1 else 's'}."
        if unpriced:
            # A rolled-up total that silently omits part of a line is a
            # number that looks complete and is not. Said on the row
            # itself, beside the figure it is missing from, rather than
            # left to a project-level count the reader has to connect.
            #
            # "Part of" rather than "no price": a line can resolve its
            # material and fail to resolve a labor rate, and the old
            # copy -- "this figure does not include them" -- was then
            # wrong in the reassuring direction, because the material
            # WAS included and only the labor was missing.
            found += (
                f" {unpriced} of {'them' if count > 1 else 'these'} "
                f"{'is' if unpriced == 1 else 'are'} missing part of "
                f"{'its' if unpriced == 1 else 'their'} cost, so this figure is lower than the work."
            )
        lines.append(EstimateLineOut(
            title=system,
            origin="counted",
            where="Takeoff spreadsheet",
            found=found,
            value=str(count),
            unit="lines" if count != 1 else "line",
            amount=cost,
        ))
    return lines


def _cost_counted(db: DbSession, project: Project, *, labor: bool,
                  totals) -> list[EstimateLineOut]:
    """The labor or material subtotal as one counted line.

    Neither section lists items: the item-by-item view is Labor pricing
    and Material pricing, which already exist and are linked from the
    section. What the ROM needs here is the number and everything that
    was assumed to reach it.
    """
    if labor:
        if not totals.labor_hours and not totals.labor_cost:
            return []
        return [EstimateLineOut(
            title="Installation labor",
            origin="counted",
            where="Labor pricing",
            found=f"{totals.labor_hours:,.0f} hours across the counted lines.",
            value=f"{totals.labor_hours:,.0f}",
            unit="hr",
            amount=totals.labor_cost,
        )]
    if not totals.material_cost:
        return []
    return [EstimateLineOut(
        title="Material",
        origin="counted",
        where="Material pricing",
        found="Priced across the counted lines.",
        amount=totals.material_cost,
    )]


def _exposures(db: DbSession, project: Project, exclude: set[uuid.UUID]) -> list[Exposure]:
    """What widens the range. See the module docstring for the gap.

    The measured-length exposure is summed over RESOLVED costs, not
    `Item.total_cost`. The stored column is the engine's figure from
    ingest, and the dollars a scaled length actually puts at risk are
    the dollars the document prints for it: a measured run stored at
    $1,000 and supplier-quoted at $5,000 was producing a +/- 20% band
    around the wrong $1,000, so the range came out $4,800-$5,200 on a
    $5,000 line whose own basis says it could be a fifth out. Same
    mismatch `resolved_lines` exists to close, applied to the spread.
    """
    exposures = list(cost_exposures(db, project, exclude=exclude))

    measured = sum(
        (line.total_cost for line in resolved_lines(db, project, exclude=exclude)
         if _is_measured(line.item)),
        Decimal("0"),
    )
    if measured > 0:
        exposures.append(Exposure("scaled", measured))
    return exposures


def _qualifications(assumptions: list[Assumption],
                    removed: dict[uuid.UUID, Decimal]) -> list[QualificationOut]:
    """The condition of the price, generated from the assumed lines.

    Deduped on `(basis, title)`: one ceiling-height assumption shared by
    forty items is one qualification, and a re-run that regenerated it
    must not make it two.

    **The deduped rows' dollars are added, not discarded.** One
    exclusion covers several subjects -- "Fire alarm by others" is a
    system row plus eleven equipment-name rows -- and each of those
    resolved its own share of the money. Keeping only the first row's
    figure reported $200 of a $500 removal, or nothing at all, depending
    on which subject happened to sort first, while the total correctly
    showed $500 gone. A qualification whose stated amount disagrees with
    the total it caused is the one kind of arithmetic a reader checks.

    Summing is right here and would be wrong at the project level, which
    is why `excluded_value` dedupes by item instead: two rows of ONE
    exclusion cover disjoint subjects, so their dollars add, whereas two
    separate exclusions may both cover one item and that item's dollars
    left the number once.

    Ordered scope exclusions first, because an exclusion changes what
    the number covers rather than how precise it is, and a reader who
    stops after three lines should have read the ones that moved money.
    Then by the basis's own width, widest first.
    """
    first: dict[tuple[str, str], Assumption] = {}
    totals: dict[tuple[str, str], Decimal] = {}
    # An overridden row is a number a person entered. It is not a
    # condition of the price -- there is nothing for a reader to check
    # beyond asking the person named on the line -- so it leaves the
    # block in the same breath it stops being assumed.
    for row in (r for r in assumptions if r.source != "estimator"):
        key = (row.basis, row.title)
        first.setdefault(key, row)
        value = removed.get(row.id)
        if value is None:
            value = row.excluded_value
        if value:
            totals[key] = totals.get(key, Decimal("0")) + Decimal(value)
    unique = list(first.values())

    def sort_key(row: Assumption):
        is_exclusion = row.basis == "standard_exclusion"
        spec = BASIS.get(row.basis)
        return (0 if is_exclusion else 1, -float(spec.spread if spec else 0), row.title)

    return [
        QualificationOut(
            title=row.title,
            found=row.found,
            why=row.why,
            where=row.where,
            basis_label=(BASIS.get(row.basis).label if BASIS.get(row.basis) else row.basis),
            excluded_value=totals.get((row.basis, row.title)),
        )
        for row in sorted(unique, key=sort_key)
    ]


def _pending_reason(db: DbSession, project: Project, totals, assumptions: list[Assumption]) -> str | None:
    """Whether this document is safe to hand to a GC.

    Counted work plus no disclosures is the dangerous state, and it is
    reachable three ways: a project that predates this feature, a run
    whose estimate job is still queued, and one whose job failed after
    its three attempts. All three previously rendered a confident
    number with an empty qualifications block.
    """
    if totals.item_count == 0 or assumptions:
        return None
    failed = db.scalars(
        select(Job).where(
            Job.project_id == project.id, Job.kind == "estimate", Job.status == "failed",
        )
    ).first()
    return GENERATION_FAILED if failed is not None else GENERATION_PENDING


def _empty_reason(db: DbSession, project: Project, totals,
                  exclude: set[uuid.UUID]) -> str | None:
    """Why this estimate is empty, when it is.

    Keyed off WHAT scope removed, not off what it cost. An exclusion
    that removed an unpriced line removed work all the same, and
    checking the dollars instead reported "the drawings were read but
    nothing was counted" over a project whose every line scope had
    taken out -- the opposite claim.
    """
    if totals.item_count > 0:
        return None
    if exclude:
        return EVERYTHING_EXCLUDED
    sheets = list(db.scalars(select(Sheet).where(
        Sheet.project_id == project.id, Sheet.superseded_at.is_(None)
    )))
    if not sheets:
        return NOTHING_PROCESSED
    if all(s.unreadable_reason for s in sheets):
        return NOTHING_READABLE
    return NOTHING_COUNTED


def build_estimate_out(db: DbSession, project: Project) -> EstimateOut:
    """One read, assembling the whole document."""
    exclude = excluded_item_ids(db, project.id)
    excluded = excluded_value(db, project.id)
    totals = rom_totals(db, project, exclude=exclude)

    assumptions = list(db.scalars(
        select(Assumption)
        .where(Assumption.project_id == project.id)
        .order_by(Assumption.section, Assumption.created_at, Assumption.id)
    ))
    removed = excluded_value_by_assumption(db, project.id)

    by_section: dict[str, list[Assumption]] = {key: [] for key in SECTIONS}
    for row in assumptions:
        by_section.setdefault(row.section, []).append(row)

    sections = []
    for key in SECTIONS:
        assumed = [_assumption_line(row, removed.get(row.id)) for row in by_section.get(key, [])]
        if key == "scope":
            counted = _scope_counted(db, project)
            subtotal = None
        elif key == "takeoff":
            counted = _takeoff_counted(db, project, exclude, totals.unpriced_by_system,
                                       totals.cost_by_system)
            subtotal = None
        elif key == "labor":
            counted = _cost_counted(db, project, labor=True, totals=totals)
            subtotal = totals.labor_cost
        else:
            counted = _cost_counted(db, project, labor=False, totals=totals)
            subtotal = totals.material_cost
        # Counted from the lines' own origins rather than from the two
        # list lengths: an overridden assumption sits in the `assumed`
        # list and renders as counted, and a tally that disagreed with
        # the rows under it would be the document contradicting itself.
        lines = counted + assumed
        sections.append(EstimateSectionOut(
            key=key,
            label=SECTION_LABELS[key],
            counted_count=sum(1 for l in lines if l.origin == "counted"),
            assumed_count=sum(1 for l in lines if l.origin == "assumed"),
            subtotal=subtotal,
            lines=lines,
        ))

    rng = budget_range(totals.direct_cost, _exposures(db, project, exclude))

    return EstimateOut(
        project_name=project.name,
        revision_set_label=project.revision_set_label,
        sheet_count=len(list(db.scalars(select(Sheet.id).where(
            Sheet.project_id == project.id, Sheet.superseded_at.is_(None)
        )))),
        direct_cost=totals.direct_cost,
        range=RangeOut(low=rng.low, high=rng.high, spread=rng.spread_dollars),
        counted_count=totals.item_count,
        assumed_count=sum(1 for a in assumptions if a.source != "estimator"),
        unpriced_count=totals.unpriced_count,
        excluded_value=excluded,
        sections=sections,
        qualifications=_qualifications(assumptions, removed),
        empty_reason=_empty_reason(db, project, totals, exclude),
        pending_reason=_pending_reason(db, project, totals, assumptions),
    )
