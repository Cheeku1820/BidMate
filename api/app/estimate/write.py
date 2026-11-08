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

from app.estimate import generate_cost, generate_scope, generate_takeoff
from app.estimate.basis import validate_assumption
from app.estimate.exclusions import excluded_from_rows
from app.takeoff.models import Assumption, Project

# The four generators are reached through their modules rather than
# imported by name. A by-name import binds the function into this
# module's namespace, which makes it unreachable from the module a
# reader would naturally patch -- and a test that cannot stub a
# generator cannot assert that a malformed one fails the run instead of
# writing a disclosure nobody can check, which is the whole point of
# the validation below. The same reason classify_job.py reaches the
# engine's agents through `from app.engine import ...`.


def _identity(row) -> tuple:
    """What makes one disclosure the same disclosure across runs.

    Accepts a stored `Assumption` or a validated dict. Deliberately NOT
    the title: a title is words for a reader, and two real disclosures
    can share one. The subject plus the basis is what actually
    identifies the thing being disclosed.
    """
    get = row.get if isinstance(row, dict) else lambda k: getattr(row, k, None)
    return (
        get("section"),
        get("subject_kind") or "project",
        str(get("subject_id")) if get("subject_id") else None,
        get("subject_ref"),
        get("basis"),
        get("title"),
    )


def generate(db: DbSession, project: Project) -> list[dict]:
    """Every assumption for one project, validated, not yet written.

    Scope runs first and its exclusions are passed to the other three:
    a line scope removed is not in the number, so disclosing its price
    basis would describe money that is not there. That ordering is the
    cascade the spec describes -- scope decides what is in, the takeoff
    counts it, labor and material price it -- expressed as an argument
    rather than as a comment.
    """
    scope = [validate_assumption(row) for row in generate_scope.scope_assumptions(db, project)]

    # Resolved against what scope just produced rather than against what
    # the last run stored, so a changed scope letter takes effect in the
    # same pass that read it -- and without writing rows to the database
    # purely to read them back.
    exclude = excluded_from_rows(db, project.id, scope)

    produced = (
        scope
        + generate_takeoff.takeoff_assumptions(db, project, exclude=exclude)
        + generate_cost.labor_assumptions(db, project, exclude=exclude)
        + generate_cost.material_assumptions(db, project, exclude=exclude)
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
    #
    # Keyed off the FULL subject, not the title. Two switchboards on one
    # job legitimately share the name "Switchboard SB-1" and are
    # different disclosures; keying on title alone meant overriding one
    # suppressed both, and a labor section carries two distinct "
    # Installation hours" disclosures (the firm's table and a derived
    # basis) that would suppress each other.
    overridden = {
        _identity(row)
        for row in db.scalars(
            select(Assumption).where(
                Assumption.project_id == project.id,
                Assumption.source == "estimator",
            )
        )
    }

    written = 0
    for row in rows:
        if _identity(row) in overridden:
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
