"""Retype, delete, and stream a stored document: PATCH changes doc_type
and is audited; DELETE removes blob then row, audited, and leaves
nothing on the undo stack; GET .../content streams the exact bytes
under the global no-store policy; all three routes are org-scoped
through load_document -> load_project, 404 never 403."""

import io
import re

import pytest
from sqlalchemy import select

from app.documents import blobstore
from app.main import app
from app.takeoff.models import Action, Document

PDF = b"%PDF-1.4\n%manage\n"


@pytest.fixture
def store():
    s = blobstore.MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


@pytest.fixture
def uploaded(client, signed_in_user, project, store):
    r = client.post(f"/api/projects/{project.id}/documents",
                    files={"file": ("E-set.pdf", io.BytesIO(PDF), "application/pdf")}, data={"doc_type": "Drawings"})
    assert r.status_code == 201, r.text
    return r.json()


def test_patch_changes_the_type_and_is_audited(client, uploaded, db, project):
    r = client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Addendum"})
    assert r.status_code == 200 and r.json()["doc_type"] == "Addendum"
    a = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_type"))
    assert a.label == "Changed E-set.pdf to Addendum" and a.before["doc_type"] == "Drawings" and a.after["doc_type"] == "Addendum"


def test_patch_refuses_an_unknown_type(client, uploaded):
    r = client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Photos"})
    assert r.status_code == 422
    assert r.json()["detail"]["message"] == "Document type must be one of Drawings, Specifications, Addendum, Scope, Other."


def test_delete_removes_blob_and_row_and_is_audited_not_undoable(client, uploaded, db, project, store):
    key = db.get(Document, uploaded["id"]).storage_key
    assert store.exists(key)
    r = client.delete(f"/api/documents/{uploaded['id']}")
    assert r.status_code == 204
    assert not store.exists(key)
    assert db.get(Document, uploaded["id"]) is None
    a = db.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_delete"))
    assert a.label == "Removed E-set.pdf"
    undo = client.post(f"/api/projects/{project.id}/undo")
    assert undo.status_code == 200 and undo.json()["performed"] is False


def test_content_streams_the_exact_bytes_privately(client, uploaded):
    r = client.get(f"/api/documents/{uploaded['id']}/content")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert "no-store" in r.headers["cache-control"]


def test_document_routes_are_org_scoped(client, uploaded, db, other_org_project, store):
    """A document under another org's project: 404 on every route."""
    from app.takeoff.models import Document as D
    foreign = D(project_id=other_org_project.id, filename="theirs.pdf", doc_type="Drawings",
                content_type="application/pdf", size_bytes=1, sha256="c" * 64,
                storage_key="orgs/x/projects/y/documents/z.pdf", uploaded_by=db.get(D, uploaded["id"]).uploaded_by)
    db.add(foreign)
    db.flush()
    assert client.get(f"/api/documents/{foreign.id}/content").status_code == 404
    assert client.patch(f"/api/documents/{foreign.id}", json={"doc_type": "Other"}).status_code == 404
    assert client.delete(f"/api/documents/{foreign.id}").status_code == 404


def test_content_disposition_is_well_formed_for_an_unusual_filename(client, project, signed_in_user, db, store):
    """A multipart filename can carry a quote or a raw CR/LF -- neither
    may reach the header un-encoded, or it either breaks or splits into
    an injected second header. The tricky name is written straight to
    the row (rather than round-tripped through a multipart POST, whose
    own encoding is a separate concern) so this isolates the header
    construction itself."""
    tricky = 'weird "name"\r\nwith-injection.pdf'
    doc = Document(
        project_id=project.id, filename=tricky, doc_type="Drawings",
        content_type="application/pdf", size_bytes=len(PDF), sha256="d" * 64,
        storage_key=f"orgs/{project.org_id}/projects/{project.id}/documents/tricky.pdf",
        uploaded_by=signed_in_user.id,
    )
    db.add(doc)
    db.flush()
    store.put(doc.storage_key, io.BytesIO(PDF), "application/pdf", len(PDF))

    r = client.get(f"/api/documents/{doc.id}/content")
    assert r.status_code == 200
    assert r.content == PDF
    cd = r.headers["content-disposition"]
    assert "\r" not in cd and "\n" not in cd
    assert re.fullmatch(r'inline; filename="[^"\r\n]*"; filename\*=UTF-8\'\'[!#$&+\-.0-9A-Z^_`a-z|~%]+', cd)
    assert "with-injection.pdf" in cd
