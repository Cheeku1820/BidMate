import uuid

import pytest
from sqlalchemy.exc import IntegrityError

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
