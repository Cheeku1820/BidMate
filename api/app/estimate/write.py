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

from sqlalchemy import delete, select, text
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

    Accepts a stored `Assumption` or a validated dict. The section plus
    the full subject plus the title: the subject alone is too coarse (a
    labor section carries a hours disclosure and a rate disclosure
    against the same project, which is why `generate_cost` puts the kind
    in `subject_ref`), and the title alone is too coarse the other way
    (two switchboards on one job legitimately share a name).

    **`basis` is deliberately NOT part of it.** It was, and that is a
    bug with a reproducible symptom: an override rewrites `basis` to
    `estimator_entered`, so the overridden row no longer matched the
    engine row it replaced, and the next run wrote the engine's version
    back beside it -- the document then showed "45 ft per device,
    Counted" and "30 ft per device, Assumed" as two live disclosures of
    one fact. The basis is a *property* of a disclosure, and the one
    property an override exists to change; identity cannot include the
    thing that changes.
    """
    get = row.get if isinstance(row, dict) else lambda k: getattr(row, k, None)
    return (
        get("section"),
        get("subject_kind") or "project",
        str(get("subject_id")) if get("subject_id") else None,
        get("subject_ref"),
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

    Serialized per project by a transaction-scoped advisory lock. Two
    estimate jobs for one project can now be in flight at once -- that
    is deliberate, see `queue.enqueue_estimate` for why collapsing them
    lost an estimator's scope decision -- and this is what keeps the two
    from being two writers of one set. The lock is held to the end of
    the transaction and released by the commit or rollback, so a worker
    that dies mid-body does not leave it stuck.
    """
    # hashtextextended over the project uuid: pg_advisory_xact_lock wants
    # a bigint, and the uuid is the natural key. A collision between two
    # different projects would only make them take turns, never produce
    # a wrong number.
    db.execute(
        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": str(project.id)},
    )

    rows = generate(db, project)

    db.execute(
        delete(Assumption).where(
            Assumption.project_id == project.id,
            Assumption.source == "engine",
        )
    )
    # An estimator's override of a generated assumption keeps that
    # assumption's identity, so a regenerated row that duplicates one
    # the estimator already settled must not reappear beside it. See
    # `_identity` for what that identity is and, in particular, for why
    # the basis is not part of it.
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
            origin=row.get("origin") or "assumed",
        ))
        written += 1
    db.flush()
    return written
