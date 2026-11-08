"""Task 9 of docs/plans/rom-estimate.md -- generation runs in the worker.

Why the worker rather than the API: `app.main` may not import anything
that opens a file, and generation is a batch walk over every item on a
project rather than work a request should be waiting on. It also runs
after a run completes, which is a thing only the queue knows about.
"""
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.jobs.schemas import JOB_KINDS, timeout_for
from app.takeoff.models import Assumption, Item, Job, Project, ReviewStatus, Sheet
from app.worker.estimate_job import run as run_estimate_job


@pytest.fixture
def processed_project(db, org, dana):
    p = Project(org_id=org.id, name="Kittle's Saxony", revision_set_label="E1.1 Rev 3",
                pricing_source="llm", pricing_note="Indiana regional basis")
    db.add(p)
    db.flush()
    s = Sheet(project_id=p.id, number="EL101", title="Lighting plan", discipline="Electrical",
              revision="Rev 2", scale="", scale_options=[], plan="showroom")
    db.add(s)
    db.flush()
    db.add(Item(project_id=p.id, sheet_id=s.id, symbol="receptacle",
                name="20A duplex receptacle", system="Power", category="Devices",
                quantity=Decimal("1"), unit="ea", status=ReviewStatus.READY, x=100, y=100,
                material_cost=Decimal("100"), labor_cost=Decimal("40"),
                labor_hours=Decimal("2"), total_cost=Decimal("140")))
    db.add(Item(project_id=p.id, sheet_id=s.id, symbol="conduit", name="Feeder to SB-1",
                system="Service and distribution", category="Raceway",
                quantity=Decimal("185"), unit="ft", status=ReviewStatus.READY,
                x=200, y=200, path=[[10, 10], [90, 90]],
                material_cost=Decimal("250"), labor_cost=Decimal("0"),
                labor_hours=Decimal("0"), total_cost=Decimal("250")))
    db.flush()
    return p


def job_for(project, dana):
    return Job(org_id=project.org_id, project_id=project.id, kind="estimate",
               requested_by=dana.id, max_attempts=3, status="running")


def _run(db, project, dana):
    job = job_for(project, dana)
    db.add(job)
    db.flush()
    run_estimate_job(db, job)
    return job


# --- the kind is registered --------------------------------------------


def test_estimate_is_a_known_job_kind():
    assert "estimate" in JOB_KINDS


def test_the_kind_has_a_wall_clock_timeout():
    """Every job body runs in a sandboxed child with a per-kind timeout
    (`app/worker/sandbox.py`). A kind with no entry would raise a
    KeyError in the worker loop rather than in a test."""
    assert timeout_for("estimate") > 0


def test_the_handler_is_registered_for_the_kind():
    from app.worker.handlers import HANDLERS, _load_handlers

    _load_handlers()
    assert "estimate" in HANDLERS


# --- what it writes ----------------------------------------------------


def test_job_writes_assumptions_for_every_section(db, processed_project, dana):
    _run(db, processed_project, dana)
    sections = {a.section for a in db.query(Assumption).all()}
    assert sections == {"scope", "takeoff", "labor", "material"}


def test_every_written_row_carries_a_basis_and_a_where(db, processed_project, dana):
    _run(db, processed_project, dana)
    rows = db.query(Assumption).all()
    assert rows
    for row in rows:
        assert row.basis
        assert row.where
        assert row.source == "engine"


def test_rerun_replaces_engine_assumptions_without_duplicating(db, processed_project, dana):
    _run(db, processed_project, dana)
    first = db.query(Assumption).count()
    assert first > 0
    _run(db, processed_project, dana)
    assert db.query(Assumption).count() == first


def test_a_rerun_after_the_drawings_changed_drops_a_stale_assumption(db, processed_project, dana):
    """The scale was set between runs, so the missing-scale disclosure
    must disappear rather than linger as a disclosure of a problem that
    no longer exists."""
    _run(db, processed_project, dana)
    assert any("scale" in a.title.lower() for a in db.query(Assumption).all())

    sheet = db.query(Sheet).filter(Sheet.project_id == processed_project.id).one()
    sheet.scale = "1/8\" = 1'-0\""
    db.flush()
    _run(db, processed_project, dana)
    assert not any("scale" in a.title.lower() for a in db.query(Assumption).all())


def test_an_estimator_row_survives_a_rerun(db, processed_project, dana):
    """CLAUDE.md: the engine never discards a person's judgment. Task 11
    tests the override path; this tests the run's side of the same rule."""
    db.add(Assumption(
        project_id=processed_project.id, section="takeoff", basis="inferred",
        subject_kind="project", title="Showroom ceiling height",
        found="Entered by Dana Whitfield", why="Fixture drop lengths depend on it",
        where="Entered by Dana Whitfield", value="16", unit="ft",
        source="estimator", created_by_user_id=dana.id,
    ))
    db.flush()
    _run(db, processed_project, dana)
    kept = db.query(Assumption).filter(Assumption.source == "estimator").all()
    assert len(kept) == 1
    assert kept[0].value == "16"


def test_a_generated_row_does_not_duplicate_one_the_estimator_settled(db, processed_project, dana):
    """An override keeps the assumption's identity, so the regenerated
    engine row for the same section and title must not reappear beside
    it -- the reader would see the same disclosure twice with two
    different numbers."""
    _run(db, processed_project, dana)
    generated = db.query(Assumption).filter(Assumption.section == "labor").first()
    assert generated is not None
    generated.source = "estimator"
    generated.created_by_user_id = dana.id
    db.flush()

    _run(db, processed_project, dana)
    same_title = db.query(Assumption).filter(Assumption.title == generated.title).all()
    assert len(same_title) == 1
    assert same_title[0].source == "estimator"


# --- the boundary ------------------------------------------------------


def test_job_refuses_an_invalid_assumption(db, processed_project, dana, monkeypatch):
    monkeypatch.setattr("app.estimate.generate_scope.scope_assumptions",
                        lambda *_, **__: [{"section": "scope", "title": "t"}])
    with pytest.raises(DomainError):
        _run(db, processed_project, dana)


def test_a_failed_run_leaves_the_previous_disclosures_in_place(db, processed_project, dana, monkeypatch):
    """A ROM with stale assumptions is wrong. A ROM with none looks
    fully counted, which is worse, so validation runs over the whole set
    before anything is deleted."""
    _run(db, processed_project, dana)
    # Committed, because that is what the worker does: handlers.run
    # commits each successful job, so the next run's failure rolls back
    # to the last good state rather than to an empty table.
    db.commit()
    before = db.query(Assumption).count()
    assert before > 0

    monkeypatch.setattr("app.estimate.generate_scope.scope_assumptions",
                        lambda *_, **__: [{"section": "scope", "title": "t"}])
    with pytest.raises(DomainError):
        _run(db, processed_project, dana)
    db.rollback()
    assert db.query(Assumption).count() == before


# --- edges -------------------------------------------------------------


def test_an_empty_project_still_completes(db, org, dana):
    """A fresh project generates its scope exclusions and nothing else.
    The job must not fail on a project with no items."""
    p = Project(org_id=org.id, name="Fresh job", revision_set_label="")
    db.add(p)
    db.flush()
    _run(db, p, dana)
    sections = {a.section for a in db.query(Assumption).all()}
    assert sections == {"scope"}


def test_a_deleted_project_takes_its_estimate_job_with_it(db, org, dana):
    """`jobs.project_id` cascades, so a project deleted between queue
    and run leaves no job for the worker to claim -- `handlers.run`
    answers `job is None` and returns.

    The `project is None` branch in the handler is therefore defence
    rather than a reachable path, kept because it costs nothing and
    mirrors `sheet_job`'s reading of a sheet that vanished. This test
    asserts the cascade that makes it unreachable, which is the fact a
    future reader actually needs.
    """
    p = Project(org_id=org.id, name="Gone", revision_set_label="")
    db.add(p)
    db.flush()
    job = job_for(p, dana)
    db.add(job)
    db.flush()
    job_id = job.id

    db.delete(p)
    db.flush()
    # Expunged first: `db.get` would otherwise answer from the identity
    # map and hand back the object the database has already dropped.
    db.expunge_all()
    assert db.get(Job, job_id) is None


# --- enqueued by the run -----------------------------------------------


def test_a_completed_run_enqueues_an_estimate(db, processed_project, dana):
    from app.jobs import queue

    job = queue.enqueue_estimate(db, processed_project, dana.id)
    assert job is not None
    assert job.kind == "estimate"


def test_only_one_estimate_job_per_project_is_in_flight(db, processed_project, dana):
    from app.jobs import queue

    assert queue.enqueue_estimate(db, processed_project, dana.id) is not None
    assert queue.enqueue_estimate(db, processed_project, dana.id) is None
