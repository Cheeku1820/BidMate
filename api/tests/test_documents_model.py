import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.documents.schemas import DOC_STATUSES
from app.takeoff.models import Document


def test_document_row_round_trips(db, project, dana):
    d = Document(
        project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
        content_type="application/pdf", size_bytes=1234, sha256="a" * 64,
        storage_key=f"orgs/{project.org_id}/projects/{project.id}/documents/x.pdf",
        uploaded_by=dana.id,
    )
    db.add(d)
    db.flush()
    got = db.get(Document, d.id)
    assert got.status == "uploaded" and got.error == "" and got.created_at is not None


def test_same_hash_twice_in_one_project_is_refused_by_the_database(db, project, dana):
    for _ in range(2):
        db.add(Document(
            project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
            content_type="application/pdf", size_bytes=1, sha256="b" * 64,
            storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id,
        ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.parametrize("status", DOC_STATUSES)
def test_every_status_in_the_closed_set_is_accepted(db, project, dana, status):
    """The constraint has to admit all four, not just the one B1 writes
    -- B2's worker writes the other three, and a constraint that refused
    'processing' would surface as the worker failing on its first real
    document."""
    d = Document(
        project_id=project.id, filename=f"{status}.pdf", doc_type="Drawings",
        content_type="application/pdf", size_bytes=1, sha256=status.ljust(64, "x"),
        storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id, status=status,
    )
    db.add(d)
    db.flush()
    assert db.get(Document, d.id).status == status


def test_a_status_outside_the_closed_set_is_refused_by_the_database(db, project, dana):
    """`status` was a bare String(20) that accepted anything. The set of
    four is the whole vocabulary any screen knows how to render, so a
    writer inventing a fifth -- 'error' for 'failed', say -- has to fail
    where it happens rather than persist and surface as a row that draws
    as nothing."""
    db.add(Document(
        project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
        content_type="application/pdf", size_bytes=1, sha256="c" * 64,
        storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id, status="error",
    ))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
