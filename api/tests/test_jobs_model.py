"""The queue's closed sets and its one-in-flight rules live in the database."""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.takeoff.models import Classification, Document, Job, ScopeStatement


def _doc(db, project, dana):
    # A fresh sha256 per call: `documents` has a (project_id, sha256)
    # unique constraint, and test_scope_kind_and_status_are_closed_sets
    # below calls this twice for the same project.
    d = Document(project_id=project.id, filename="E.pdf", doc_type="Drawings", content_type="application/pdf",
                 size_bytes=3, sha256=uuid.uuid4().hex.ljust(64, "0"), storage_key="k", uploaded_by=dana.id)
    db.add(d); db.flush(); return d


def test_job_kind_is_a_closed_set(db, project):
    # "render" joined the closed set in B3 (test_render_model.py) -- this
    # picks a kind that stays invalid so this test keeps testing the
    # constraint rather than the membership of one particular value.
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="bogus", status="queued"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_job_status_is_a_closed_set(db, project):
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="classify", status="error"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_document_has_at_most_one_read_in_flight(db, project, dana):
    d = _doc(db, project, dana)
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="read", document_id=d.id, status="done"))
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="read", document_id=d.id, status="queued"))
    db.flush()  # a finished read plus one queued is fine
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="read", document_id=d.id, status="running"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_project_has_at_most_one_classify_in_flight(db, project):
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="classify", status="queued", run_id=uuid.uuid4()))
    db.flush()
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="classify", status="queued", run_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_scope_kind_and_status_are_closed_sets(db, project, dana):
    # Savepoints, not plain db.rollback(): the whole test session is one
    # open transaction with no intervening commit (this suite's
    # convention -- see test_action_log.py's
    # test_deleting_a_project_with_actions_is_restricted_not_cascaded), so
    # a bare db.rollback() after the first failed insert would discard the
    # fixture data (project, dana) the second half of this test still
    # needs. begin_nested() scopes each rollback to just its own attempt.
    d = _doc(db, project, dana)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0,
                                  kind="maybe", text="x", quote="x", status="found", run_id=uuid.uuid4()))
            db.flush()
    d = _doc(db, project, dana)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0,
                                  kind="excluded", text="x", quote="x", status="maybe", run_id=uuid.uuid4()))
            db.flush()


def test_one_classification_per_run(db, project):
    run = uuid.uuid4()
    db.add(Classification(project_id=project.id, run_id=run, specs_by_tag={}, labor_rate=78.0,
                          material_factor=1.0, source="deterministic"))
    db.flush()
    db.add(Classification(project_id=project.id, run_id=run, specs_by_tag={}, labor_rate=78.0,
                          material_factor=1.0, source="deterministic"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
