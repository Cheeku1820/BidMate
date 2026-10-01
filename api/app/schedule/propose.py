"""Phases proposed, never created without a press (phases-and-timeline.md §9).

`detect_from_sheet_numbers` is this stream's own detector -- sheet
families by the letters before the first digit, which is how the firm's
own two-phase bid tells its phases apart (`E-1.0` against `XE-1.0`). The
plan screen (stream F) replaces the input by posting its own
`phases_proposed` list; the preview and the confirm stay exactly as they
are, because the estimator's press is what creates anything.
"""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.errors import DomainError
from app.identity.models import User
from app.schedule import copy as words
from app.schedule.phases import (
    _add_template_lines,
    _lines_snapshot,
    _snapshot_phase,
    first_phase,
    phases_for,
)
from app.schedule.schemas import ProposedPhase, ProposeOut
from app.takeoff import actions
from app.takeoff.models import Phase, Project, Sheet

_LEADING_LETTERS = re.compile(r"^\s*([A-Za-z]+)")


def _family(number: str) -> str:
    """The phase marker a sheet number carries, which is what the
    letters *before* the discipline letter say.

    The firm's own two-phase bid is the case to get right: phase 1 is
    `E-1.0`, `E-2.0`, `ED-1.0`, `ED-2.0` and phase 2 is `XE-1.0`,
    `XED-1.0`, `XES-1.1`. Grouping on the whole leading run would split
    each phase into an `E`/`ED` pair, because the trailing letter names
    the sheet's kind (D for demolition, S for site), not its phase.
    Everything before the discipline letter is the marker: "" and "X".
    """
    match = _LEADING_LETTERS.match(number or "")
    if match is None:
        return ""
    run = match.group(1).upper()
    return run.split("E", 1)[0] if "E" in run else run


def _family_label(family: str, numbers: list[str]) -> str:
    """Named after the sheets themselves -- "E sheets", "XE sheets" --
    so the estimator recognises the group in the drawing index rather
    than reading a label the product invented."""
    prefixes = sorted({_LEADING_LETTERS.match(n).group(1).upper() for n in numbers if _LEADING_LETTERS.match(n)})
    shortest = min(prefixes, key=len) if prefixes else family
    return f"{shortest} sheets"


def detect_from_sheet_numbers(db: DbSession, project: Project) -> list[ProposedPhase]:
    """Plan sheets grouped by the letters their number starts with. Two
    or more families is a phasing proposal; one family is a project with
    no phasing to find, and says so rather than proposing a single phase
    that changes nothing."""
    sheets = list(db.scalars(
        select(Sheet).where(
            Sheet.project_id == project.id,
            Sheet.superseded_at.is_(None),
            Sheet.kind == "plan",
        )
    ))
    families: dict[str, list[Sheet]] = {}
    for sheet in sheets:
        families.setdefault(_family(sheet.number), []).append(sheet)
    if len(families) < 2:
        return []
    proposed = []
    for family in sorted(families, key=lambda f: (len(f), f)):
        rows = sorted(families[family], key=lambda s: s.number)
        numbers = [s.number for s in rows]
        proposed.append(ProposedPhase(
            name=_family_label(family, numbers),
            sheet_numbers=numbers,
            sheet_ids=[s.id for s in rows],
        ))
    return proposed


def preview_proposal(db: DbSession, project: Project, phases: list[ProposedPhase]) -> ProposeOut:
    """Writes nothing. Every sheet named has to be on this project --
    an id from somewhere else is refused here rather than silently
    dropped at apply time."""
    if not phases:
        return ProposeOut(phases=[], note=words.NO_PHASING_FOUND)
    known = {s.id for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}
    for phase in phases:
        if any(sheet_id not in known for sheet_id in phase.sheet_ids):
            raise DomainError("sheet_not_found", "One of those sheets isn't on this project.")
    sheets = sum(len(p.sheet_ids) for p in phases)
    return ProposeOut(phases=phases, note=words.proposal_note(len(phases), sheets))


def apply_proposal(db: DbSession, *, actor: User, project: Project, phases: list[ProposedPhase]) -> None:
    """One `phase_propose_apply` action carrying every phase created and
    every sheet moved, so the whole proposal is one press to undo."""
    if not phases:
        raise DomainError("nothing_to_apply", "There are no phases to apply.")
    preview_proposal(db, project, phases)  # the same tenancy check, before anything is written

    first = first_phase(db, project, create=True)
    existing = phases_for(db, project.id)
    sheets_before = {
        str(s.id): (str(s.phase_id) if s.phase_id else None)
        for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))
    }
    # The first proposed phase renames the implicit first phase rather
    # than adding beside it: a project that has never been phased has
    # exactly one "Phase 1" holding everything, and the drawings'
    # first family is that same set of work under its real name.
    rename_first = len(existing) == 1 and existing[0].name == "Phase 1"
    # Read before the loop runs: `existing[0]` is the same live object
    # the rename below mutates, so reading its name at commit time would
    # snapshot the new name as the old one and undo would restore
    # nothing.
    first_name_before = existing[0].name if existing else "Phase 1"
    created: list[Phase] = []
    sheets_after: dict[str, str | None] = {}

    for index, proposed in enumerate(phases):
        if index == 0 and rename_first:
            phase = first
            phase.name = proposed.name
            target: uuid.UUID | None = None
        else:
            phase = Phase(project_id=project.id, name=proposed.name, sort_order=len(existing) + len(created))
            db.add(phase)
            db.flush()
            _add_template_lines(db, project.org_id, phase)
            created.append(phase)
            target = phase.id
        for sheet_id in proposed.sheet_ids:
            sheet = db.get(Sheet, sheet_id)
            sheet.phase_id = target
            sheets_after[str(sheet_id)] = str(target) if target else None
    db.flush()

    order_after = [str(p.id) for p in phases_for(db, project.id)]
    actions.commit(
        db, actor=actor, project_id=project.id, kind="phase_propose_apply",
        label=f"Set up {len(phases)} phases from the drawings",
        before={
            "sheets": {key: sheets_before[key] for key in sheets_after},
            "order": [str(p.id) for p in existing],
            "first_name": first_name_before,
        },
        after={
            "phases": [_snapshot_phase(p) | {"lines": _lines_snapshot(db, p.id)} for p in created],
            "sheets": sheets_after,
            "order": order_after,
            "first_name": phases[0].name if rename_first else first_name_before,
        },
    )
