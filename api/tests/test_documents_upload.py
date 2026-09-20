"""Upload rules, verified through the HTTP layer with a memory store:
stored bytes and row; duplicate within a project refused by name; the
same bytes in another project stored again; unsupported refused without
parsing; other org's project 404; the audit row carries no bytes."""

import hashlib
import io
import uuid

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import sessionmaker

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
    assert body["filename"] == "E-set.pdf" and body["doc_type"] == "Drawings" and body["status"] == "processing"
    assert body["size_bytes"] == len(PDF)
    # The hash is stored and is what the duplicate rule keys on, but it
    # is deliberately not on the wire -- spec §7 keeps "hash" out of
    # anything estimator-facing, and a field the client receives is one
    # copy change away from being rendered. Asserted on the row instead.
    assert "sha256" not in body
    row = db.get(Document, body["id"])
    assert row.sha256 == hashlib.sha256(PDF).hexdigest()
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


def test_a_filename_too_long_to_store_is_refused_before_hashing(client, signed_in_user, project, store):
    long_name = "a" * 297 + ".pdf"  # 301 chars, over Document.filename's 300-char column
    r = _upload(client, project.id, name=long_name)
    assert r.status_code == 422
    # The code, not a substring of the message: the message is copy and
    # is expected to be reworded, and an assertion on its words turns a
    # copy edit into a red test that says nothing about behaviour.
    assert r.json()["detail"]["code"] == "filename_too_long"
    assert store.blobs == {}


def test_two_uploads_of_the_same_bytes_racing_are_refused_by_the_database(client, signed_in_user, project, db, store):
    """Deterministic stand-in for two uploads of the same bytes in
    flight together (screen C drops files in parallel): both would pass
    the service's pre-flush `select` clean, so the database -- not the
    app -- has to be the tiebreaker. A `before_flush` hook lands and
    commits a colliding row, through a second session on the same
    engine, at the exact moment the service's own flush is about to
    insert -- after its own `select` already came back empty.

    Fixture data (project/org/dana) is only flushed, not committed, at
    this point, so it commits here first -- the racer's insert needs
    `project` and `dana` to already be visible outside this session, and
    a bare `db.rollback()` after the race would otherwise erase them
    along with the failed attempt (see test_action_log.py's note on the
    same hazard).
    """
    db.commit()
    sha = hashlib.sha256(PDF).hexdigest()
    Racer = sessionmaker(bind=db.get_bind())
    fired = False

    def _insert_racer(session, flush_context, instances):
        nonlocal fired
        if fired or not any(isinstance(o, Document) and o.sha256 == sha for o in session.new):
            return
        fired = True
        racer = Racer()
        try:
            racer.add(Document(
                id=uuid.uuid4(), project_id=project.id, filename="racer.pdf", doc_type="Drawings",
                content_type="application/pdf", size_bytes=len(PDF), sha256=sha,
                storage_key=f"orgs/{project.org_id}/projects/{project.id}/documents/racer.pdf",
                uploaded_by=signed_in_user.id,
            ))
            racer.commit()
        finally:
            racer.close()

    event.listen(db, "before_flush", _insert_racer)
    try:
        r = _upload(client, project.id, name="mine.pdf")
    finally:
        event.remove(db, "before_flush", _insert_racer)

    assert fired, "the race window never fired -- the test didn't exercise the race"
    assert r.status_code == 409
    assert "racer.pdf" in r.json()["detail"]["message"]
    assert len(store.blobs) == 0


def test_a_storage_failure_leaves_no_row_and_no_action(client, signed_in_user, project, db):
    """If `store.put()` raises after the document's own flush, nothing
    persists: the row was flushed but never committed, which is what a
    real request-scoped session's close-without-commit would do too.
    Checked from a second, independent session -- not `db` itself, which
    would still see its own uncommitted flush -- so this proves nothing
    landed durably, not just that `db` hasn't been asked to look yet."""

    class _ExplodingStore:
        blobs: dict = {}

        def put(self, key, stream, content_type, size):
            raise RuntimeError("storage unavailable")

        def open(self, key):
            raise blobstore.BlobNotFound(key)

        def delete(self, key):
            pass

        def exists(self, key):
            return False

    app.dependency_overrides[blobstore.get_blob_store] = lambda: _ExplodingStore()
    try:
        r = _upload(client, project.id)
    finally:
        app.dependency_overrides.pop(blobstore.get_blob_store, None)

    assert r.status_code == 500

    Checker = sessionmaker(bind=db.get_bind())
    checker = Checker()
    try:
        assert checker.scalar(select(Document).where(Document.project_id == project.id)) is None
        assert checker.scalar(select(Action).where(Action.project_id == project.id, Action.kind == "document_add")) is None
    finally:
        checker.close()


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
    assert set(action.after) == {"id", "filename", "doc_type", "size_bytes", "sha256", "status"}
    assert action.after["filename"] == "E-set.pdf"


def test_a_pricing_upload_accepts_xlsx_and_queues_no_read(client, signed_in_user, project, db, store):
    from app.takeoff.models import Job
    r = _upload(
        client, project.id, name="codale.xlsx", data=b"PK\x03\x04fake",
        doc_type="Pricing", ctype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert r.status_code == 201, r.text
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "read")) == 0


def test_a_pricing_upload_refuses_a_pdf_and_drawings_refuse_xlsx(client, signed_in_user, project, store):
    r = _upload(client, project.id, name="q.pdf", data=b"%PDF-1.4", doc_type="Pricing", ctype="application/pdf")
    assert r.status_code == 415
    r = _upload(client, project.id, name="q.xlsx", data=b"PK", doc_type="Drawings", ctype="application/octet-stream")
    assert r.status_code == 415
