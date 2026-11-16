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
from app.takeoff import confidence
from app.takeoff.models import Project, ScopeStatement, Sheet
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
        for line in lines:
            if not line.priced or line.item.origin != "counted":
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
        material, _, _ = self._whole_job
        return material


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

    return _unidentified(lines, sheets, averages, labor_rate)
