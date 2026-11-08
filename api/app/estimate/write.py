"""The one write path for generated assumptions.

Separate from `app.worker.estimate_job` on purpose. The *job* -- claiming
work off the queue, the sandbox, the retry -- is the worker's. The
*rule* about what replacing a generated set means is domain logic, and
it belongs beside the generators where it can be read next to them and
tested without a queue.

**The engine never discards a person's judgment** (CLAUDE.md). A run
deletes and rewrites only `source="engine"` rows. An estimator's
override is `source="estimator"` and is never touched, the same
protection an *Estimator approved* item gets from `merge.py` -- which is
the same rule, applied to a different table.

Every dict passes `validate_assumption` before it is written. A
generator that cannot fill all six fields fails the run rather than
writing a disclosure nobody can check; `ingest.validate_warning` refuses
a partial warning for the same reason.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.estimate.basis import validate_assumption
from app.estimate.exclusions import excluded_from_rows
from app.estimate.generate_cost import labor_assumptions, material_assumptions
from app.estimate.generate_scope import scope_assumptions
from app.estimate.generate_takeoff import takeoff_assumptions
from app.takeoff.models import Assumption, Project


def generate(db: DbSession, project: Project) -> list[dict]:
    """Every assumption for one project, validated, not yet written.

    Scope runs first and its exclusions are passed to the other three:
    a line scope removed is not in the number, so disclosing its price
    basis would describe money that is not there. That ordering is the
    cascade the spec describes -- scope decides what is in, the takeoff
    counts it, labor and material price it -- expressed as an argument
    rather than as a comment.
    """
    scope = [validate_assumption(row) for row in scope_assumptions(db, project)]

    # Resolved against what scope just produced rather than against what
    # the last run stored, so a changed scope letter takes effect in the
    # same pass that read it -- and without writing rows to the database
    # purely to read them back.
    exclude = excluded_from_rows(db, project.id, scope)

    produced = (
        scope
        + takeoff_assumptions(db, project, exclude=exclude)
        + labor_assumptions(db, project, exclude=exclude)
        + material_assumptions(db, project, exclude=exclude)
    )
    return [validate_assumption(row) for row in produced]


def regenerate(db: DbSession, project: Project) -> int:
    """Replace this project's generated assumptions. Returns the count.

    Validation runs over the whole set before anything is deleted, so a
    generator bug leaves the previous run's disclosures in place rather
    than leaving the document with none. A ROM with stale assumptions is
    wrong; a ROM with no assumptions looks fully counted, which is worse.
    """
    rows = generate(db, project)

    db.execute(
        delete(Assumption).where(
            Assumption.project_id == project.id,
            Assumption.source == "engine",
        )
    )
    # An estimator's override of a generated assumption keeps that
    # assumption's identity, so a regenerated row that duplicates one
    # the estimator already settled must not reappear beside it.
    overridden = {
        (section, title)
        for section, title in db.execute(
            select(Assumption.section, Assumption.title).where(
                Assumption.project_id == project.id,
                Assumption.source == "estimator",
            )
        ).all()
    }

    written = 0
    for row in rows:
        if (row["section"], row["title"]) in overridden:
            continue
        db.add(Assumption(
            project_id=project.id,
            section=row["section"],
            subject_kind=row["subject_kind"],
            subject_id=row.get("subject_id"),
            subject_ref=row.get("subject_ref"),
            title=row["title"],
            found=row["found"],
            why=row["why"],
            where=row["where"],
            basis=row["basis"],
            value=row.get("value"),
            unit=row.get("unit"),
            source="engine",
        ))
        written += 1
    db.flush()
    return written
