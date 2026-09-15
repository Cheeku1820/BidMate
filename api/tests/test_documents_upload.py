"""Upload rules, verified through the HTTP layer with a memory store:
stored bytes and row; duplicate within a project refused by name; the
same bytes in another project stored again; unsupported refused without
parsing; other org's project 404; the audit row carries no bytes."""

import hashlib
import io

import pytest
from sqlalchemy import select

from app.documents import blobstore
from app.main import app
from app.takeoff.models import Action, Document, Project

PDF = b"%PDF-1.4\n%fake but enough for a hash\n"


@pytest.fixture
def store():
    s = blobstore.MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


def _upload(client, project_id, name="E-set.pdf", data=PDF, doc_type="Drawings", ctype="application/pdf"):
    return client.post(
        f"/api/projects/{project_id}/documents",
        files={"file": (name, io.BytesIO(data), ctype)},
        data={"doc_type": doc_type},
    )


def test_upload_stores_bytes_and_a_row(client, signed_in_user, project, db, store):
    r = _upload(client, project.id)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "E-set.pdf" and body["doc_type"] == "Drawings" and body["status"] == "uploaded"
    assert body["sha256"] == hashlib.sha256(PDF).hexdigest() and body["size_bytes"] == len(PDF)
    row = db.get(Document, body["id"])
    assert row.storage_key == f"orgs/{project.org_id}/projects/{project.id}/documents/{row.id}.pdf"
    assert store.open(row.storage_key).read() == PDF


def test_second_identical_upload_in_the_same_project_is_refused_by_name(client, signed_in_user, project, db, store):
    assert _upload(client, project.id, name="first.pdf").status_code == 201
    r = _upload(client, project.id, name="second.pdf")
    assert r.status_code == 409
    assert "first.pdf" in r.json()["detail"]["message"]
    assert db.scalar(select(Document).where(Document.project_id == project.id, Document.filename == "second.pdf")) is None
    assert len(store.blobs) == 1


def test_same_bytes_in_another_project_are_stored_again(client, signed_in_user, project, org, db, store):
    other = Project(org_id=org.id, name="Another job", revision_set_label="")
    db.add(other)
    db.flush()
    assert _upload(client, project.id).status_code == 201
    assert _upload(client, other.id).status_code == 201
    assert len(store.blobs) == 2


def test_a_non_pdf_is_refused_without_being_stored(client, signed_in_user, project, db, store):
    r = _upload(client, project.id, name="notes.docx", data=b"PK\x03\x04", ctype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.status_code == 415
    assert "notes.docx" in r.json()["detail"]["message"] and "PDF" in r.json()["detail"]["message"]
    assert store.blobs == {}


def test_a_pdf_extension_with_a_non_pdf_content_type_is_refused(client, signed_in_user, project, store):
    r = _upload(client, project.id, name="sneaky.pdf", ctype="text/plain")
    assert r.status_code == 415


def test_an_unknown_doc_type_is_refused(client, signed_in_user, project, store):
    r = _upload(client, project.id, doc_type="Photos")
    assert r.status_code == 422


def test_other_orgs_project_is_not_found_not_forbidden(client, other_org_project, store):
    assert _upload(client, other_org_project.id).status_code == 404
    assert client.get(f"/api/projects/{other_org_project.id}/documents").status_code == 404


def test_list_returns_the_projects_documents_oldest_first(client, signed_in_user, project, store):
    _upload(client, project.id, name="a.pdf", data=PDF + b"a")
    _upload(client, project.id, name="b.pdf", data=PDF + b"b")
    r = client.get(f"/api/projects/{project.id}/documents")
    assert r.status_code == 200
    assert [d["filename"] for d in r.json()] == ["a.pdf", "b.pdf"]


def test_upload_is_audited_without_bytes(client, signed_in_user, project, db, store):
    _upload(client, project.id)
    action = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_add"))
    assert action is not None
    assert action.label == "Uploaded E-set.pdf as Drawings"
    assert action.after["filename"] == "E-set.pdf" and "content" not in action.after
    assert PDF.decode("latin-1") not in str(action.after)
