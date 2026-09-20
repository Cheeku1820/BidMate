"""Retype, delete, and stream a stored document: PATCH changes doc_type
and is audited; DELETE removes the row then the blob, audited, and
leaves nothing on the undo stack; GET .../content streams the exact
bytes as an attachment, no-store and nosniff, and says what to do when
the stored file is gone; all three routes are org-scoped through
load_document -> load_project, 404 never 403."""

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
    assert r.json()["detail"]["message"] == "Document type must be one of Drawings, Specifications, Addendum, Scope, Other, Pricing."


def test_patch_refuses_crossing_the_pricing_line_either_way(client, signed_in_user, project, store, uploaded):
    # A drawing (a PDF) can't become a price sheet -- the read job only
    # parses PDFs, and a spreadsheet's rows come back through the
    # price-sheet parser instead.
    r = client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Pricing"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_doc_type"
    assert "price sheet" in r.json()["detail"]["message"] and "drawing" in r.json()["detail"]["message"]

    # A retype among the non-Pricing types is unaffected.
    r2 = client.patch(f"/api/documents/{uploaded['id']}", json={"doc_type": "Other"})
    assert r2.status_code == 200

    # And a price sheet can't be retyped into a drawing either.
    pricing = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("codale.xlsx", io.BytesIO(b"PK\x03\x04fake"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "Pricing"},
    ).json()
    r3 = client.patch(f"/api/documents/{pricing['id']}", json={"doc_type": "Drawings"})
    assert r3.status_code == 422
    assert r3.json()["detail"]["code"] == "invalid_doc_type"


def test_delete_removes_row_and_blob_and_is_audited_not_undoable(client, uploaded, db, project, store):
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


def test_delete_commits_the_row_before_touching_storage(client, uploaded, db, project, store):
    """I3: the old ordering called `store.delete` before the route's own
    `db.commit()`, so a storage failure rolled the whole transaction
    back -- the row's deletion never took effect, and the estimator's
    remove silently didn't happen. The fix commits the row first: the
    remove always takes effect, and a storage failure only leaves an
    orphan blob nothing references -- ROADMAP.md §2.2's reaper problem,
    not a dangling row and not a delete that quietly failed."""
    key = db.get(Document, uploaded["id"]).storage_key
    calls = []
    original = store.delete

    def failing_delete(k):
        calls.append(k)
        raise RuntimeError("storage down")

    store.delete = failing_delete
    try:
        res = client.delete(f"/api/documents/{uploaded['id']}")
    finally:
        store.delete = original

    assert res.status_code == 204
    assert calls == [key]
    assert db.get(Document, uploaded["id"]) is None
    assert client.get(f"/api/projects/{project.id}/documents").json() == []


def test_content_streams_the_exact_bytes_privately(client, uploaded):
    r = client.get(f"/api/documents/{uploaded['id']}/content")
    assert r.status_code == 200
    assert r.content == PDF
    assert r.headers["content-type"].startswith("application/pdf")
    assert "no-store" in r.headers["cache-control"]
    # An uploaded drawing set often arrives under a GC's NDA: served as
    # an attachment so it does not render inside a page that framed it,
    # and nosniff so an untrusted upload cannot pick its own type.
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"


def test_content_streams_a_pricing_upload_with_its_own_content_type(client, signed_in_user, project, store):
    """A price sheet's content route must serve it as the spreadsheet it
    is -- not as `application/pdf`, which every Pricing upload got
    before this was fixed."""
    xlsx = b"PK\x03\x04fake"
    r = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("codale.xlsx", io.BytesIO(xlsx), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"doc_type": "Pricing"},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    content = client.get(f"/api/documents/{doc_id}/content")
    assert content.status_code == 200
    assert content.content == xlsx
    assert content.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert content.headers["x-content-type-options"] == "nosniff"


def test_a_pricing_upload_is_not_listed_with_the_drawing_set(client, signed_in_user, project, store, uploaded, db):
    """A price sheet is never read, so it stays `uploaded` for good --
    and the intake screens render an `uploaded` document as a drawing
    still being read, polling for a finish that never comes. It is a
    project document (stored, audited, streamable by id) but not part of
    the drawing set the documents list is."""
    r = client.post(
        f"/api/projects/{project.id}/documents",
        files={"file": ("codale.csv", io.BytesIO(b"Item,Unit price\nx,1\n"), "text/csv")},
        data={"doc_type": "Pricing"},
    )
    assert r.status_code == 201, r.text
    pricing_id = r.json()["id"]

    listed = client.get(f"/api/projects/{project.id}/documents").json()
    assert [d["id"] for d in listed] == [uploaded["id"]]
    assert pricing_id not in {d["id"] for d in listed}
    # Still reachable by id: the material-pricing preview loads it that way.
    assert client.get(f"/api/documents/{pricing_id}/content").status_code == 200

    from app.documents import service
    from app.takeoff.models import Project
    p = db.get(Project, project.id)
    assert {str(d.id) for d in service.list_documents(db, p, include_pricing=True)} == {uploaded["id"], pricing_id}


def test_content_says_what_to_do_when_the_stored_file_is_gone(client, uploaded, store):
    """A row whose blob is missing is reachable without a bug here -- a
    storage lifecycle rule, a restore from a backup taken after the blob
    was removed. The estimator gets a recovery action, not a 500, and
    not a sentence about storage."""
    store.blobs.clear()

    r = client.get(f"/api/documents/{uploaded['id']}/content")

    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["code"] == "document_unavailable"
    assert "E-set.pdf" in detail["message"]
    assert "Upload it again" in detail["message"]
    lowered = detail["message"].lower()
    assert "please" not in lowered and "successfully" not in lowered and "!" not in detail["message"]
    for internal in ("hash", "bucket", "s3", "object storage", "blob", "minio"):
        assert internal not in lowered, f"{internal!r} is an internal, not estimator-facing copy"


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
    assert re.fullmatch(r'attachment; filename="[^"\r\n]*"; filename\*=UTF-8\'\'[!#$&+\-.0-9A-Z^_`a-z|~%]+', cd)
    assert "with-injection.pdf" in cd
