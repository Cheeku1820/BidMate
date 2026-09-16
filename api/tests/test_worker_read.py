import io
import os
import uuid

import pymupdf
import pytest
from sqlalchemy import select

from app.documents.blobstore import MemoryBlobStore
from app.jobs import copy, queue
from app.takeoff.models import Document, Item, ReviewStatus, ScopeStatement, Sheet
from app.worker import __main__ as worker, blobs


@pytest.fixture(autouse=True)
def inline(monkeypatch):
    monkeypatch.setenv("WORKER_INLINE", "1")
    store = MemoryBlobStore()
    monkeypatch.setattr(blobs, "get_blob_store", lambda: store)
    return store


def _pdf(text="", pages=1, encrypt=False) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        p = doc.new_page(width=1224, height=792)
        if text:
            p.insert_text((72, 72), text)
            p.draw_rect(pymupdf.Rect(100, 100, 900, 700))   # a path, so the page counts as a drawing
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o") if encrypt else doc.tobytes()


def _pdf_pages(texts: list[str]) -> bytes:
    """One page per string, each with its own title-block text -- unlike
    `_pdf`, which repeats one string across every page -- so two
    distinctly-numbered sheets are detected."""
    doc = pymupdf.open()
    for text in texts:
        p = doc.new_page(width=1224, height=792)
        p.insert_text((72, 72), text)
        p.draw_rect(pymupdf.Rect(100, 100, 900, 700))
    return doc.tobytes()


def _stored(db, project, dana, store, data, doc_type="Drawings", name="E.pdf"):
    d = Document(project_id=project.id, filename=name, doc_type=doc_type, content_type="application/pdf",
                 size_bytes=len(data), sha256=uuid.uuid4().hex * 2, storage_key=f"k/{uuid.uuid4()}", uploaded_by=dana.id)
    db.add(d); db.flush()
    store.put(d.storage_key, io.BytesIO(data), "application/pdf", len(data))
    return d


def _run_all(db):
    db.commit()
    while worker.tick("t"):
        pass


def test_read_stores_pages_sheets_and_marks_processed(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)   # inline mode: the handler uses the test session
    d = _stored(db, project, dana, inline, _pdf("E2.1 FIRST FLOOR POWER PLAN  SCALE: 1/8\" = 1'-0\"", pages=2))
    queue.enqueue_read(db, d)
    _run_all(db)
    db.refresh(d)
    assert d.status == "processed" and d.page_count == 2 and d.error == ""
    sheets = list(db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))))
    assert sheets and all(s.region and s.width_pt == 1224 for s in sheets)


def test_read_of_a_spec_stores_context_and_scope(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("DIVISION 26 ELECTRICAL\nEXCLUSIONS\n- Site lighting and pole bases.\n"), doc_type="Specifications", name="spec.pdf")
    queue.enqueue_read(db, d)
    _run_all(db)
    db.refresh(d)
    assert d.status == "processed" and "DIVISION 26" in d.context_text
    [s] = db.scalars(select(ScopeStatement).where(ScopeStatement.document_id == d.id))
    assert (s.kind, s.status, s.page_index) == ("excluded", "found", 0) and "Site lighting" in s.text


def test_an_encrypted_file_fails_with_the_password_copy(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("x", encrypt=True))
    queue.enqueue_read(db, d)
    _run_all(db)
    db.refresh(d)
    assert d.status == "failed" and d.error == "Couldn't read — the file is password protected. Upload an unlocked copy."


def test_garbage_fails_with_the_resave_copy(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, b"%PDF-1.4 nope")
    queue.enqueue_read(db, d)
    _run_all(db)
    db.refresh(d)
    assert d.status == "failed" and d.error.startswith("Couldn't read this file.")


def test_rereading_keeps_sheet_ids_and_decided_scope_and_refinds_found(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("DIVISION 26\nEXCLUSIONS\n- Site lighting.\n- Fire alarm.\n"), doc_type="Scope", name="s.pdf")
    queue.enqueue_read(db, d); _run_all(db)
    found = list(db.scalars(select(ScopeStatement).where(ScopeStatement.document_id == d.id)))
    found[0].status, found[0].decided_by = "dismissed", dana.id
    db.commit()
    queue.enqueue_read(db, d); _run_all(db)
    after = list(db.scalars(select(ScopeStatement).where(ScopeStatement.document_id == d.id)))
    assert len(after) == 2 and {s.status for s in after} == {"dismissed", "found"}
    assert any(s.id == found[0].id for s in after)


def test_a_missing_blob_is_terminal_with_the_unavailable_copy(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = Document(project_id=project.id, filename="gone.pdf", doc_type="Drawings", content_type="application/pdf",
                 size_bytes=1, sha256="f" * 64, storage_key="k/none", uploaded_by=dana.id)
    db.add(d); db.flush()
    queue.enqueue_read(db, d); _run_all(db)
    db.refresh(d)
    assert d.status == "failed" and "isn't available any more" in d.error


_TWO_PAGES = [
    "E1.1 FIRST FLOOR POWER PLAN  SCALE: 1/8\" = 1'-0\"",
    "E2.1 SECOND FLOOR POWER PLAN  SCALE: 1/8\" = 1'-0\"",
]
_ONE_PAGE = _TWO_PAGES[:1]


def _replace_stored_bytes(store, d, data):
    """Re-store the same document row under a new set of bytes -- what a
    replaced upload looks like from the worker's side: same document id
    and storage key, a fresh read job."""
    store.put(d.storage_key, io.BytesIO(data), "application/pdf", len(data))


def test_a_vanished_page_with_an_approved_item_keeps_the_sheet_and_marks_it_page_gone(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf_pages(_TWO_PAGES))
    queue.enqueue_read(db, d); _run_all(db)
    sheet2 = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id), Sheet.page_index == 2)).one()
    approved = Item(project_id=project.id, sheet_id=sheet2.id, symbol="receptacle", name="20A duplex receptacle",
                     system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.APPROVED,
                     x=100, y=100)
    unapproved = Item(project_id=project.id, sheet_id=sheet2.id, symbol="receptacle", name="Data outlet",
                       system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY,
                       x=200, y=200)
    db.add(approved); db.add(unapproved); db.commit()

    _replace_stored_bytes(inline, d, _pdf_pages(_ONE_PAGE))
    queue.enqueue_read(db, d); _run_all(db)

    still = db.get(Sheet, sheet2.id)
    assert still is not None and still.unreadable_reason == copy.PAGE_GONE
    remaining = list(db.scalars(select(Item).where(Item.sheet_id == sheet2.id)))
    assert [i.id for i in remaining] == [approved.id]


def test_a_vanished_page_with_no_approved_items_deletes_the_sheet(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf_pages(_TWO_PAGES))
    queue.enqueue_read(db, d); _run_all(db)
    sheet2 = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id), Sheet.page_index == 2)).one()
    sheet2_id = sheet2.id
    db.add(Item(project_id=project.id, sheet_id=sheet2.id, symbol="receptacle", name="Data outlet",
                system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY,
                x=100, y=100))
    db.commit()

    _replace_stored_bytes(inline, d, _pdf_pages(_ONE_PAGE))
    queue.enqueue_read(db, d); _run_all(db)

    assert db.get(Sheet, sheet2_id) is None
