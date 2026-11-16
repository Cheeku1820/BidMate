"""The completion pass: a number for the work the engine could not count.

docs/specs/estimate-without-asking.md, slice 2. The defect this exists
to fix, in the spec's own words:

    Handed less information, the product returns a *smaller* number
    rather than a wider one.

Every assumption the ROM wrote before this was derived from items that
already existed (`generate_takeoff.py`), so a sheet the engine read
poorly contributed zero dollars and zero disclosures. That is the exact
failure `BUILD-STAGES.md` names as the worst outcome the product can
produce -- *"silence reads as completeness"* -- and an estimator who
trusts a silently incomplete sheet loses the bid the same way a
confidently wrong one does.

**Every case writes the same thing: one companion allowance line,
attached to a real sheet, carrying money the counted lines do not.** Why
this shape and not the two obvious alternatives:

- **Not an assumption carrying a positive amount.** Only items add money
  (`rom_totals` sums `countable_items`), and CLAUDE.md holds that an
  assumption may only ever subtract. A disclosure beside an unchanged
  total was the original bug, not the fix.
- **Not a cost written onto the counted line.** That would overwrite what
  the engine read with what this module guessed, and `merge.py` -- the
  one write path for engine output -- would fight it on the next run.
  The counted line keeps saying exactly what was counted.

Three rules hold across every case below:

1. **Nothing counted means nothing guessed.** Every quantity and every
   dollar is relative to what this project itself counted, through
   `siblings.py` and `_class_average`. There are no device constants in
   this file, and `sibling_stats` returning None is what stands every
   comparing case down at once.
2. **`Sheet.scale` is never written.** The single most dangerous write
   in this design, and the answer is simply not to make it. See
   `_unscaled`.
3. **Nothing is approved and nothing is written here.** This module is
   pure read-and-propose; `write_completion` does the writing.
"""
from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.estimate import complete_copy as copy
from app.estimate import building_type, siblings
from app.takeoff import confidence, undo
from app.takeoff.models import Action, Item, Project, ReviewStatus, ScopeStatement, Sheet
from app.takeoff.totals import ResolvedLine, resolved_lines

# A sheet whose scale is absent, or which carries two labels and so has
# no single one. Promoted out of `generate_takeoff.py` so one list
# governs both the disclosure and the allowance -- they describe the
# same sheets and must not be able to disagree about which.
NO_SINGLE_SCALE = ("", "mixed", "unknown", "none")

# Units that mean a length rather than a count.
MEASURED_UNITS = ("ft", "lf", "feet")

# How far below its siblings a sheet has to count before the shortfall
# is assumed rather than believed.
#
# **The spec leaves this threshold deliberately open and says to pick
# something defensible, make it one named constant, and state it in the
# disclosure copy.** Half of the typical sheet: a plan sheet carrying
# less than half what its siblings carry is either genuinely sparse --
# in which case an estimator deletes one allowance -- or it read badly,
# which is the case this is for. A tighter threshold (0.8, say) would
# fire on normal variation between a corridor sheet and an open office
# and bury the real signal in allowances nobody trusts.
#
# Expected to move once a real bid set has been through it.
THIN_FRACTION = 0.5

# What share of a job's counted electrical cost each system is worth,
# by kind of building. Case 5's whole arithmetic.
#
# A share, never a dollar figure, because that is what keeps the rule
# relative: a share of zero is zero, so a project with nothing counted
# produces no system allowance rather than a constant. One cell changed
# here moves every project of that kind, which is the point of keeping
# it as one table a person can read.
#
# **Expected to move once a real bid set has been through it.** These
# are deliberately conservative: the failure to avoid is an allowance so
# large it swamps the counted work, because an estimator who sees one
# absurd line stops trusting every other line on the document.
#
# "default" is used when a document names the work but nothing says what
# kind of building this is. The *existence* evidence there is the
# document itself, which is the strongest kind; only the amount is
# generic.
SYSTEM_SHARES: dict[str, dict[str, float]] = {
    "default": {"Fire alarm": 0.06, "Low voltage": 0.05, "Life safety": 0.03},
    "school": {"Fire alarm": 0.08, "Low voltage": 0.07, "Life safety": 0.03},
    "healthcare": {"Fire alarm": 0.10, "Low voltage": 0.10, "Life safety": 0.05},
    "warehouse": {"Fire alarm": 0.05, "Low voltage": 0.03, "Life safety": 0.02},
    "office": {"Fire alarm": 0.07, "Low voltage": 0.08, "Life safety": 0.03},
    "multifamily": {"Fire alarm": 0.07, "Low voltage": 0.04, "Life safety": 0.03},
    "retail": {"Fire alarm": 0.06, "Low voltage": 0.05, "Life safety": 0.03},
    "industrial": {"Fire alarm": 0.05, "Low voltage": 0.04, "Life safety": 0.02},
}

# How a document says it carries work in a system. Substring matching
# over stored text, the same shape and the same justification as
# `building_type.TYPE_VOCABULARY` and
# `generate_scope.StandardExclusion.vocabulary`: extracted document text
# is untrusted input (ROADMAP invariant 11), and a drawing cannot steer
# a `str.find`.
SYSTEM_VOCABULARY: dict[str, tuple[str, ...]] = {
    "Fire alarm": (
        "fire alarm", "division 28", "smoke detector", "pull station", "notification appliance",
        "horn strobe", "horn/strobe", "facp", "annunciator",
    ),
    "Low voltage": (
        "division 27", "structured cabling", "data outlet", "telecom room",
        "access control", "cctv", "security camera", "nurse call", "paging system",
    ),
    "Life safety": (
        "exit sign", "emergency lighting", "egress lighting", "emergency egress",
    ),
}

# The lump-sum unit. Case 1's companion carries money for devices that
# were already counted, so giving it a device count would make the
# spreadsheet read as twice as many devices as the drawing shows.
LUMP_SUM = "ls"

_CENTS = Decimal("0.01")


def _cents(value: Decimal) -> Decimal:
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)


# --- what this project's own priced work costs ----------------------------

class _ClassAverage:
    """What a device costs on this job, per unit, by system.

    Read off `resolved_lines` rather than `Item`'s stored cost columns,
    for the reason `totals.resolved_lines` gives at length: the stored
    columns hold the engine's first guess and ignore every supplier
    quote, company price, and number an estimator typed. An allowance
    priced from them would be $140 for a line a supplier quoted at $500.

    Falls back from the line's own system to the whole job, and reports
    None when nothing on the project priced at all -- which stands case
    1 down rather than reaching for a constant.
    """

    def __init__(self, lines: list[ResolvedLine]) -> None:
        self._by_system: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        total_material = total_hours = total_qty = Decimal("0")
        # Case 5 takes a share of *all* the counted electrical work, so
        # this one deliberately includes measured runs -- conduit is
        # counted electrical work and a fire alarm allowance sized
        # against a job's devices alone would understate it. Kept
        # separate from the per-unit figures above, which must count
        # devices only.
        counted_total = Decimal("0")
        for line in lines:
            if line.priced and line.item.origin == "counted":
                counted_total += line.total_cost
        self._counted_total = counted_total
        for line in lines:
            if not line.priced or line.item.origin != "counted":
                continue
            # Devices only. Feet and devices are not the same quantity,
            # and summing them into one denominator is a per-unit figure
            # of nothing: on a job with two 60-device sheets at $6,000
            # each, adding 10,000 ft of conduit at $10,000 dropped the
            # per-device average from $100 to $1.52 and an empty-sheet
            # allowance from $6,000 to $130. `siblings.plan_sheet_counts`
            # already excludes measured lines from its own counts for
            # exactly this reason; the two had to agree.
            if _measured(line):
                continue
            qty = Decimal(line.item.quantity or 0)
            if qty <= 0:
                continue
            system = line.item.system
            material, hours, counted = self._by_system.get(
                system, (Decimal("0"), Decimal("0"), Decimal("0")))
            self._by_system[system] = (
                material + line.material_cost,
                hours + line.labor_hours,
                counted + qty,
            )
            total_material += line.material_cost
            total_hours += line.labor_hours
            total_qty += qty
        self._whole_job = (total_material, total_hours, total_qty)

    def per_unit(self, system: str | None = None) -> tuple[Decimal, Decimal] | None:
        """`(material_per_unit, hours_per_unit)`, or None."""
        candidates = [self._by_system.get(system or ""), self._whole_job]
        for candidate in candidates:
            if candidate is None:
                continue
            material, hours, qty = candidate
            if qty > 0:
                return material / qty, hours / qty
        return None

    @property
    def total_cost(self) -> Decimal:
        """Every dollar this project counted and priced, measured runs
        included. Case 5's share base."""
        return self._counted_total


def _money(per_unit: tuple[Decimal, Decimal], quantity: Decimal,
           labor_rate: Decimal) -> dict[str, Decimal]:
    material_per, hours_per = per_unit
    material = _cents(material_per * quantity)
    hours = _cents(hours_per * quantity)
    return {
        "material_cost": material,
        "labor_hours": hours,
        "labor_cost": _cents(hours * labor_rate),
        "total_cost": _cents(material + hours * labor_rate),
    }


def _labor_rate(lines: list[ResolvedLine]) -> Decimal:
    """The blended rate this project's own priced work resolved at.

    Derived, never a constant: the firm's rate is already in the
    resolution chain, and reading it back out of the lines means an
    allowance is priced at the same rate as everything beside it.
    """
    cost = hours = Decimal("0")
    for line in lines:
        if line.labor_resolved:
            cost += line.labor_cost
            hours += line.labor_hours
    return (cost / hours) if hours > 0 else Decimal("0")


# --- the cases -------------------------------------------------------------

def _line(*, case: str, sheet: Sheet, name: str, system: str, category: str,
          quantity: Decimal, unit: str, basis: str, method: str,
          adjustments: list[str], money: dict[str, Decimal],
          title: str, found: str, fix: str, why: str, where: str,
          subject_kind: str = "sheet") -> dict[str, Any]:
    """One companion allowance, in the shape `write_completion` writes
    and `completion_assumptions` discloses.

    `status` is `ready`, always. A guessed line is not *Needs
    attention*: that label demands an acknowledgment at the export,
    which is precisely the nagging this slice removes, and the
    confidence meter is what tells an estimator whether to look. It is
    not *Estimator approved* either -- no code path writes that.
    """
    score, reasons = confidence.score(method, adjustments)
    return {
        "case": case,
        "subject_kind": subject_kind,
        "sheet_id": sheet.id,
        "sheet_number": sheet.number,
        "name": name,
        "system": system,
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "origin": "assumed",
        "status": "ready",
        "basis": basis,
        "confidence": score,
        "confidence_reasons": reasons,
        "title": title,
        "found": found,
        "why": why,
        "fix": fix,
        "where": where,
        **money,
    }


def _unidentified(lines: list[ResolvedLine], sheets: dict[uuid.UUID, Sheet],
                  averages: _ClassAverage, labor_rate: Decimal) -> list[dict]:
    """Case 1 -- a cluster counted but never identified.

    The most common gap, and the only one where the quantity is solid
    and the money is not: Counting found 47 shapes and Classification
    could not name them, so the line carries no dependable price.

    One companion per sheet rather than per cluster. Forty unpriced
    clusters on one sheet is one problem with one fix -- say what the
    symbols are -- and forty identical allowances would describe it as
    forty.
    """
    by_sheet: dict[uuid.UUID, list[ResolvedLine]] = {}
    for line in lines:
        if line.priced or line.item.origin != "counted":
            continue
        if line.item.path or (line.item.unit or "").strip().lower() in MEASURED_UNITS:
            continue  # a measured run with no price is case 2's problem
        by_sheet.setdefault(line.item.sheet_id, []).append(line)

    rows: list[dict] = []
    for sheet_id, affected in sorted(by_sheet.items(), key=lambda kv: sheets[kv[0]].number):
        sheet = sheets[sheet_id]
        devices = sum(int(line.item.quantity or 0) for line in affected)
        if devices <= 0:
            continue
        # Priced against the system most of the unpriced devices sit in,
        # falling back to the whole job inside `per_unit`.
        system = affected[0].item.system
        per_unit = averages.per_unit(system)
        if per_unit is None:
            # Nothing on this project priced at all, so there is no
            # "typical cost on this job" to be relative to. Standing
            # down is the honest answer; reaching for a constant is not.
            continue
        rows.append(_line(
            case="unidentified", sheet=sheet,
            name=copy.UNIDENTIFIED["name"].format(sheet=sheet.number),
            system=system, category="Allowance",
            # A lump sum, not a device count. The counted line already
            # says 47; a companion carrying 47 as well would make the
            # spreadsheet read as 94 devices on a sheet that has 47.
            quantity=Decimal("1"), unit=LUMP_SUM,
            basis="class_average", method="counted_unidentified", adjustments=[],
            money=_money(per_unit, Decimal(devices), labor_rate),
            title=copy.UNIDENTIFIED["title"].format(sheet=sheet.number),
            found=copy.UNIDENTIFIED["found"].format(
                devices=copy.plural(devices, "device"), sheet=sheet.number),
            why=copy.UNIDENTIFIED["why"],
            fix=copy.UNIDENTIFIED["fix"].format(sheet=sheet.number),
            where=copy.UNIDENTIFIED["where"].format(sheet=sheet.number),
        ))
    return rows


def _measured(line: ResolvedLine) -> bool:
    item = line.item
    return bool(item.path) or (item.unit or "").strip().lower() in MEASURED_UNITS


def _unscaled(lines: list[ResolvedLine], sheets: dict[uuid.UUID, Sheet],
              labor_rate: Decimal) -> list[dict]:
    """Case 2 -- measured runs on a sheet with no confirmed scale.

    Today those items are *Missing information* and contribute nothing
    to the number, so the ROM is silently short by whatever that footage
    is worth -- and wire and conduit are a large share of material cost
    (ROADMAP 2.1 calls them the largest single threat to a defensible
    total).

    **The item keeps its `missing` status and `Sheet.scale` is never
    written.** Both deliberate, and the second one is the most dangerous
    write this design could have made: a stored scale is
    indistinguishable from a confirmed one, so writing a guess there
    would release every blocked item on the sheet and let the export
    through. What changes is only that the money is in the number and
    disclosed; the firewall stays shut until a person sets the scale.

    The cost per foot is this project's own: the resolved cost of
    measured runs on sheets that *do* have a confirmed scale. With no
    such run anywhere, there is nothing to be relative to and the case
    stands down.
    """
    confirmed_cost = confirmed_hours = confirmed_feet = Decimal("0")
    by_sheet: dict[uuid.UUID, list[ResolvedLine]] = {}

    for line in lines:
        if not _measured(line) or line.item.origin != "counted":
            continue
        sheet = sheets.get(line.item.sheet_id)
        if sheet is None:
            continue
        if (sheet.scale or "").strip().lower() in NO_SINGLE_SCALE:
            # Only runs that are NOT already in the number. A measured
            # row on an unscaled sheet can still resolve a price -- its
            # `missing` status does not keep it out of `rom_totals`,
            # which applies no status filter by design -- and an
            # allowance covering it bills the same footage twice. The
            # case is "measured runs that cannot convert to feet", and a
            # priced one evidently did.
            if not line.priced:
                by_sheet.setdefault(sheet.id, []).append(line)
        elif line.priced:
            confirmed_cost += line.material_cost
            confirmed_hours += line.labor_hours
            confirmed_feet += Decimal(line.item.quantity or 0)

    if confirmed_feet <= 0:
        return []
    per_foot = (confirmed_cost / confirmed_feet, confirmed_hours / confirmed_feet)

    rows: list[dict] = []
    for sheet_id, affected in sorted(by_sheet.items(), key=lambda kv: sheets[kv[0]].number):
        sheet = sheets[sheet_id]
        feet = sum(Decimal(line.item.quantity or 0) for line in affected)
        if feet <= 0:
            continue
        rows.append(_line(
            case="unscaled", sheet=sheet,
            name=copy.UNSCALED["name"].format(sheet=sheet.number),
            system=affected[0].item.system, category="Allowance",
            quantity=Decimal("1"), unit=LUMP_SUM,
            basis="scaled", method="measured_unconfirmed", adjustments=[],
            money=_money(per_foot, feet, labor_rate),
            title=copy.UNSCALED["title"].format(sheet=sheet.number),
            found=copy.UNSCALED["found"].format(
                lines=copy.plural(len(affected), "measured line"), sheet=sheet.number),
            why=copy.UNSCALED["why"],
            fix=copy.UNSCALED["fix"].format(sheet=sheet.number),
            where=copy.UNSCALED["where"].format(sheet=sheet.number),
        ))
    return rows


def _against_siblings(counts: list[tuple[str, int]], with_items: set[str],
                      sheets: dict[uuid.UUID, Sheet],
                      averages: _ClassAverage, labor_rate: Decimal) -> list[dict]:
    """Cases 3 and 4 -- a sheet thin or empty against its siblings.

    One calculation, two cases: an empty sheet is the thin case with a
    count of zero. Splitting them would mean two thresholds that could
    drift apart, and the only real difference is the sentence printed.

    Stands down entirely when `sibling_stats` returns None, which is
    both review focus 1 (nothing counted anywhere) and review focus 2 (a
    single-sheet project, where a sheet would be compared against
    itself).
    """
    stats = siblings.sibling_stats(counts)
    if stats is None:
        return []

    per_unit = averages.per_unit()
    if per_unit is None:
        return []

    by_number = {sheet.number: sheet for sheet in sheets.values()}
    floor = stats.median * THIN_FRACTION
    listed = _listed(list(stats.sheet_numbers))

    rows: list[dict] = []
    for number, counted in counts:
        if counted >= floor:
            continue
        sheet = by_number.get(number)
        if sheet is None:
            continue
        shortfall = stats.median - counted
        if shortfall <= 0:
            continue

        empty = counted == 0
        # A sheet with zero DEVICES but real counted work on it -- a
        # riser, a single-line diagram, a sheet of measured feeder runs
        # -- was read correctly and has no devices to find. Case 4's
        # definition is "produced no items at all"; this produced items.
        # Guessing devices onto it is the fabrication the slice exists
        # to prevent, and the thin comparison is meaningless there too.
        if empty and number in with_items:
            continue
        words = copy.EMPTY if empty else copy.THIN
        # A page that rendered or read only partly is a named
        # adjustment, not a different kind of guess -- the count is over
        # an incomplete picture of the sheet, which the scale already
        # has a word for.
        adjustments = ["partial_page"] if empty and sheet.render_status == "failed" else []

        rows.append(_line(
            case="empty" if empty else "thin", sheet=sheet,
            name=words["name"].format(sheet=sheet.number),
            # Deliberately not a system read off the thin sheet: there
            # may be nothing on it to read. The whole job's blended rate
            # prices it, and the line says so.
            system="Unassigned", category="Allowance",
            quantity=Decimal(shortfall), unit="EA",
            basis="class_average", method="class_average_sibling",
            adjustments=adjustments,
            money=_money(per_unit, Decimal(shortfall), labor_rate),
            title=words["title"].format(sheet=sheet.number),
            found=words["found"].format(
                sheet=sheet.number, counted=copy.plural(counted, "device"),
                median=copy.plural(stats.median, "device"),
                shortfall=copy.plural(shortfall, "device")),
            why=words["why"],
            fix=words["fix"].format(sheet=sheet.number),
            where=words["where"].format(sheet=sheet.number, sheets=listed),
        ))
    return rows


def _document_mentions(db: DbSession, project: Project,
                       sheets: dict[uuid.UUID, Sheet]) -> dict[str, str]:
    """`{system: the verbatim sentence that named it}`.

    The strongest of the three kinds of evidence a system allowance can
    rest on: a real quote on a real page. Read out of scope statements
    and stored schedule text, both of which the read job already put in
    the database -- this opens no file.
    """
    found: dict[str, str] = {}

    def observe(text: str) -> None:
        low = text.lower()
        for system, words in SYSTEM_VOCABULARY.items():
            if system in found:
                continue
            for word in words:
                if word in low:
                    found[system] = text.strip()
                    break

    for statement in db.scalars(
        select(ScopeStatement).where(ScopeStatement.project_id == project.id)
    ):
        for text in (statement.edited_text, statement.text, statement.quote):
            if text:
                observe(text)
    for sheet in sheets.values():
        if sheet.schedule_text:
            observe(sheet.schedule_text)
    return found


def _covered_systems(lines: list[ResolvedLine]) -> set[str]:
    """Which guessable systems this job demonstrably counted work in.

    **Reads the item's own name, not only its system**, and that is the
    whole point of the function. The classifier has no "Fire alarm"
    system at all -- `engine.contracts.RESOLVE_SYSTEMS` is Lighting,
    Power, Distribution, Low voltage, Life safety, Unknown -- so a
    counted smoke detector classifies as *Life safety*. Comparing system
    strings therefore reported "no fire alarm work was found on this
    set" on every project in existence, including ones carrying eight
    counted smoke detectors, and added an allowance on top of work that
    was already in the number.

    This is the same trap `generate_scope.StandardExclusion.vocabulary`
    documents from the other direction: "a counted fire-alarm device may
    classify as 'Life safety', but so do exit signs, which ARE Division
    26 work this estimate includes". One vocabulary, read against both
    the system and the name, is what keeps the two cases apart -- a
    smoke detector covers fire alarm, an exit sign does not.
    """
    covered: set[str] = set()
    for line in lines:
        if line.item.origin != "counted":
            continue
        text = " ".join([
            line.item.system or "", line.item.name or "",
            line.item.category or "", line.item.description or "",
        ]).lower()
        for system, words in SYSTEM_VOCABULARY.items():
            if system.lower() in text or any(word in text for word in words):
                covered.add(system)
        # An exact system match still counts on its own, for the systems
        # the classifier does name (Life safety, Low voltage).
        if line.item.system:
            covered.add(line.item.system)
    return covered


def _system_allowances(db: DbSession, project: Project, lines: list[ResolvedLine],
                       sheets: dict[uuid.UUID, Sheet], averages: _ClassAverage,
                       labor_rate: Decimal) -> list[dict]:
    """Case 5 -- a system a job of this kind carries and this one never
    found at all. No panels, no lighting, no fire alarm.

    The weakest rung on the ladder, and the copy says so on the line.
    Two guards keep it from fabricating a building:

    - **Nothing counted, nothing to take a share of.** The amount is a
      share of this project's own counted electrical cost, so a share of
      zero is zero.
    - **No building type and no document naming the work, no line.** A
      system allowance invented with no sense of the job is exactly the
      fabricated number the spec forbids. An *inferred* type is enough
      to run -- the spec's rule is infer it, disclose it, ask about it,
      never block on it.
    """
    counted_cost = averages.total_cost
    if counted_cost <= 0:
        return []

    counted_systems = _covered_systems(lines)

    mentions = _document_mentions(db, project, sheets)

    kind = project.building_type
    if kind is None:
        inferred = building_type.infer_building_type(db, project)
        kind = inferred[0] if inferred else None

    shares = SYSTEM_SHARES.get(kind or "", SYSTEM_SHARES["default"])
    # Systems to consider: the ones a job of this kind carries, plus any
    # the documents named outright. A document-named system runs even
    # with no building type, because the evidence for its *existence* is
    # the document rather than the building.
    candidates = set(mentions)
    if kind is not None:
        candidates |= set(shares)
    if not candidates:
        return []

    # `Item.sheet_id` is NOT NULL, so there is no such thing as an item
    # without a sheet. The lowest-numbered plan sheet is a nominal
    # home, and `where` says so rather than letting it read as the place
    # the work was found.
    plan_sheets = sorted(
        (s for s in sheets.values() if s.kind == "plan"), key=lambda s: s.number)
    anchor = plan_sheets[0] if plan_sheets else None
    if anchor is None:
        return []

    per_unit = averages.per_unit()
    if per_unit is None:
        return []

    rows: list[dict] = []
    for system in sorted(candidates):
        if system in counted_systems:
            continue
        share = shares.get(system) or SYSTEM_SHARES["default"].get(system)
        if not share:
            continue

        dollars = _cents(counted_cost * Decimal(str(share)))
        if dollars <= 0:
            continue

        quote = mentions.get(system)
        if quote:
            found = copy.SYSTEM_EVIDENCE_DOCUMENT.format(system=system.lower(), quote=quote)
            basis_sentence = copy.SYSTEM_BASIS_DOCUMENT.format(system=system.lower())
        else:
            reading = (
                f"This is read as a {kind} job, and a {kind} job normally carries it."
                if kind else ""
            )
            found = copy.SYSTEM_EVIDENCE_BUILDING_TYPE.format(
                system=system.lower(), reading=reading).strip()
            basis_sentence = copy.SYSTEM_BASIS_BUILDING_TYPE

        # The share is a share of the whole cost, and the material/labor
        # split follows the job's own split so the hours land on the
        # schedule as well as the dollars on the ROM.
        material_per, hours_per = per_unit
        units = (dollars / material_per) if material_per > 0 else Decimal("0")
        rows.append(_line(
            case="system", subject_kind="system", sheet=anchor,
            name=copy.SYSTEM["name"].format(system=system),
            system=system, category="Allowance",
            quantity=Decimal("1"), unit=LUMP_SUM,
            basis="class_average", method="class_average_system", adjustments=[],
            money={
                "material_cost": dollars,
                "labor_hours": _cents(hours_per * units),
                "labor_cost": _cents(hours_per * units * labor_rate),
                "total_cost": _cents(dollars + hours_per * units * labor_rate),
            },
            title=copy.SYSTEM["title"].format(system=system.lower()),
            found=found,
            why=copy.SYSTEM["why"].format(system=system.lower()),
            fix=copy.SYSTEM["fix"].format(system=system),
            where=copy.SYSTEM["where"].format(sheet=anchor.number, basis=basis_sentence),
        ))
    return rows


_LISTED_MAX = 6


def _listed(values: list[str]) -> str:
    """A readable, bounded list of sheet numbers. Mirrors
    `generate_takeoff._listed` -- a disclosure naming two hundred sheets
    is a wall, and one naming none cannot be checked."""
    values = [v for v in values if v]
    if not values:
        return "the other plan sheets"
    if len(values) > _LISTED_MAX:
        shown = values[:_LISTED_MAX]
        return f"{', '.join(shown)} and {len(values) - _LISTED_MAX} more"
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} and {values[-1]}"


def completion_lines(db: DbSession, project: Project, *,
                     exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """Every companion allowance this project's gaps call for.

    Reads and proposes; writes nothing. `exclude` is the set of item ids
    scope removed, passed through from `write.generate` -- an allowance
    covering excluded work would be money in the number for something
    out of scope, which is the same argument the other three generators
    make for taking the parameter.
    """
    lines = resolved_lines(db, project, exclude=exclude)
    if not lines:
        # Nothing counted means nothing guessed. Every case below is
        # relative to this project's own counts, so with no counts there
        # is no base and a number produced anyway would be a fabricated
        # building.
        return []

    sheets = {
        s.id: s for s in db.scalars(
            select(Sheet).where(Sheet.project_id == project.id, Sheet.superseded_at.is_(None))
        )
    }
    averages = _ClassAverage(lines)
    labor_rate = _labor_rate(lines)

    return [
        *_unidentified(lines, sheets, averages, labor_rate),
        *_unscaled(lines, sheets, labor_rate),
        *_against_siblings(siblings.plan_sheet_counts(db, project),
                           siblings.sheets_with_items(db, project), sheets,
                           averages, labor_rate),
        *_system_allowances(db, project, lines, sheets, averages, labor_rate),
    ]


# --- writing ---------------------------------------------------------------
#
# Deliberately NOT routed through `merge_sheet`, even though completion
# is engine output and that is the one write path for engine output. Its
# merge key is `(sheet_number, source_tag)`, and a companion has no
# symbol tag to key on -- inventing one would fabricate a cluster that
# `resolve_apply.py` would then offer to apply to "every one like this"
# across the set. What this path borrows instead is `merge.py`'s two
# *rules*, which are the part that matters: never overwrite a person's
# judgment, and never resurrect what a person deleted.

# Where a companion records which gap it covers. `evidence` is already
# the item's "why should I believe this" field and is already JSONB, so
# no column is needed -- and the spec's own description of a completion
# row is that it shows why the work is believed to be there *in place
# of* an evidence crop.
CASE_KEY = "completion_case"
# The system this companion was written FOR, stored beside the case.
#
# Deliberately not read back off `Item.system`, which is the bug this
# key exists to fix: identity used the live column, so an estimator
# moving a Power allowance to Lighting made the next run's Power
# identity unmatched and a second row appeared beside theirs. Worse, a
# deletion recorded the edited system, so the identity it suppressed was
# not the identity the next run proposed and the allowance came back
# from the dead. Identity cannot include a field an estimator can edit
# -- the same argument `write._identity` makes for leaving `basis` out.
SYSTEM_KEY = "completion_system"
# The `version` this module last wrote. What tells the engine's own
# rewrite from a person's edit, now that a rewrite bumps `version` like
# every other write path does (`app.takeoff.concurrency`).
ENGINE_VERSION_KEY = "engine_version"


def _identity(sheet_id, case: str | None, system: str | None) -> tuple:
    """What makes one companion the same companion across runs.

    The sheet it sits on, the gap it covers, and the system it was
    written for. Deliberately not the name (an estimator may retitle
    it), not the amount (that is what a re-run is for), and not the
    confidence.
    """
    return (str(sheet_id), case, system)


def _identity_of(item) -> tuple:
    """Read entirely out of `evidence`, never off the live columns, so an
    estimator's edit cannot move a row's identity out from under the
    engine."""
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    return _identity(item.sheet_id, evidence.get(CASE_KEY), evidence.get(SYSTEM_KEY))


def _untouched(item) -> bool:
    """Whether the engine still owns this row.

    Approved, rejected, no longer `ready`, or at a `version` this module
    did not write: any one of them and the row is a person's. It is
    skipped rather than rewritten, and it is not deleted either.

    The version test reads the engine's own recorded version rather than
    `version == 1`. It has to: a reprice bumps `version` so a client
    holding a stale one is refused, and comparing against 1 would make
    the engine's first rewrite look like somebody's edit and freeze the
    row forever -- never updated again, never removed when its gap
    closed.
    """
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    return (
        item.status is ReviewStatus.READY
        and item.approved_by_user_id is None
        and item.rejected_at is None
        and item.version == evidence.get(ENGINE_VERSION_KEY)
    )


def _deliberately_deleted(db: DbSession, project: Project) -> set[tuple]:
    """The identities a person deleted and has not undone.

    Deletion is a hard row delete, so the items table cannot tell "an
    estimator deleted this" from "this never existed" -- but the action
    log can, and it is the system of record for exactly this question.
    The same walk `merge._deliberately_deleted` does, over the same
    liveness rule (`undo._live`), keyed on this module's identity rather
    than on the symbol tag.

    A set rather than a count, unlike merge's: a companion identity is
    unique per project by construction, so one deletion suppresses one
    row and there is no "three untagged items, one deleted" case.
    """
    rows = undo._action_summaries(db, project.id)
    live = undo._live(rows)
    ids = [r.id for r in rows if r.kind == "delete" and live[r.id]]
    if not ids:
        return set()

    deleted: set[tuple] = set()
    for action in db.scalars(select(Action).where(Action.id.in_(ids))):
        snapshot = action.before or {}
        if snapshot.get("origin") != "assumed":
            continue
        evidence = snapshot.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        case = evidence.get(CASE_KEY)
        if case is None:
            continue
        # Both halves out of `evidence`, same as `_identity_of`. Reading
        # the system off the snapshot's live column meant a deletion
        # after an edit suppressed the wrong identity and the allowance
        # was resurrected.
        deleted.add(_identity(snapshot.get("sheet_id"), case, evidence.get(SYSTEM_KEY)))
    return deleted


def write_completion(db: DbSession, project: Project) -> int:
    """Write this project's companion allowances. Returns how many.

    Three outcomes per existing companion, and the asymmetry between
    them is the whole design:

    - **A person has touched it** -- approved, edited, rejected. Left
      exactly as it is, and the run's matching line is dropped rather
      than written beside it.
    - **The engine still owns it and the gap is still there.** Rewritten
      in place, so a changed class average moves the allowance.
    - **The engine still owns it and the gap has closed** -- somebody
      classified the symbol, set the scale, counted the sheet. Removed,
      because otherwise the real price lands beside a guess for the same
      work and the number double-counts it.
    """
    proposed = {_identity(line["sheet_id"], line["case"], line["system"]): line
                for line in completion_lines(db, project)}

    existing = list(db.scalars(
        select(Item)
        .where(Item.project_id == project.id, Item.origin == "assumed")
        .order_by(Item.id)
        .with_for_update()
    ))

    written = 0
    for item in existing:
        identity = _identity_of(item)
        if not _untouched(item):
            # Theirs. Drop the line that matched it so it is not written
            # a second time beside their version.
            proposed.pop(identity, None)
            continue
        line = proposed.pop(identity, None)
        if line is None:
            db.delete(item)
            continue
        _apply(item, line)
        written += 1

    for identity in _deliberately_deleted(db, project):
        proposed.pop(identity, None)

    for line in proposed.values():
        db.add(_new_item(project, line))
        written += 1

    db.flush()
    return written


def _new_item(project: Project, line: dict) -> Item:
    item = Item(
        id=uuid.uuid4(), project_id=project.id, sheet_id=line["sheet_id"],
        # No symbol tag, by the argument above, and no symbol glyph
        # either: nothing was read off the page, so there is no shape to
        # draw. `x`/`y`/`path`/`placements` stay null for the same
        # reason, which is why `BlueprintCanvas` gains a coordinate
        # guard.
        symbol="", source_tag="",
        name=line["name"], description="", system=line["system"],
        category=line["category"], quantity=line["quantity"], unit=line["unit"],
        status=ReviewStatus.READY, origin="assumed",
    )
    # `version` defaults to 1 on an unflushed row, and a brand-new row
    # has nothing to bump from.
    item.version = 1
    _apply(item, line, fresh=True)
    return item


def _apply(item: Item, line: dict, *, fresh: bool = False) -> None:
    """Set every field this module owns. Deliberately does not touch
    `notes`, `phase_id`, or any approval/rejection column -- the same
    fields `merge._overwrite` leaves alone, for the same reason: they
    are the estimator's, never the engine's.

    Bumps `version` on a rewrite, exactly as `merge._overwrite` does.
    Without it a reviewer holding the row at $100 could approve it after
    a reprice moved it to $564 and get no stale-version refusal
    (`app.takeoff.concurrency`), which is the one protection every other
    single-item write path provides. The engine records the version it
    wrote so its own bump does not read as somebody's edit -- see
    `_untouched`.
    """
    if not fresh:
        item.version += 1
    item.name = line["name"]
    item.system = line["system"]
    item.category = line["category"]
    item.quantity = line["quantity"]
    item.unit = line["unit"]
    item.origin = "assumed"
    item.material_cost = line["material_cost"]
    item.labor_hours = line["labor_hours"]
    item.labor_cost = line["labor_cost"]
    item.total_cost = line["total_cost"]
    item.confidence = line["confidence"]
    item.confidence_reasons = line["confidence_reasons"]
    item.evidence = {
        # In place of an evidence crop: why the work is believed to be
        # there, and where to look.
        "detail": line["found"],
        "sheet": line["sheet_number"],
        "has_image": False,
        # The identity triple's two mutable halves, frozen here so an
        # estimator's later edit cannot move them, plus the version this
        # write produced.
        CASE_KEY: line["case"],
        SYSTEM_KEY: line["system"],
        ENGINE_VERSION_KEY: item.version,
    }


def completion_assumptions(db: DbSession, project: Project, *,
                           exclude: set[uuid.UUID] | None = None) -> list[dict]:
    """One disclosure per companion, in the shape the three existing
    generators return, so `validate_assumption` accepts them unchanged.

    **An allowance without this is the anti-goal the spec names first:**
    "an assumed number that does not say it is assumed". The whole
    licence to add money nobody counted comes from the disclosure, so
    these are built from the same lines the items were written from
    rather than from the items -- one source, no way to drift.
    """
    return [
        {
            "section": "takeoff",
            "subject_kind": "sheet",
            "subject_id": line["sheet_id"],
            # Two companions can share a sheet (an unidentified cluster
            # and an unscaled run), and `write._identity` is
            # (section, subject, subject_ref, title) -- so the case goes
            # in `subject_ref` to keep them from collapsing into one
            # disclosure the way `generate_cost` puts its kind there.
            "subject_ref": line["case"],
            "basis": line["basis"],
            "title": line["title"],
            "found": line["found"],
            "why": line["why"],
            # An `Assumption` has no `fix` column -- its four fields are
            # found/why/basis/where. The completion line's "what to
            # check" sentence is appended to `where`, which is the field
            # that already answers "where do I go", rather than being
            # dropped.
            "where": f"{line['where']} {line['fix']}",
            "origin": "assumed",
            "source": "engine",
        }
        for line in completion_lines(db, project, exclude=exclude)
    ]
