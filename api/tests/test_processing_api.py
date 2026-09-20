"""The API drives the worker: an upload queues a read, Start takeoff
queues a run, the processing response reports both in stage words only
(spec §7.1, ROADMAP invariant 7), and removing a document takes its
jobs and its sheets with it."""
import json
import uuid

import pytest
from sqlalchemy import select

from app.documents import blobstore
from app.jobs import copy, queue
from app.main import app
from app.takeoff.models import Action, Document, Item, Job, ReviewStatus, Sheet

FORBIDDEN = ("source", "attempt", "llm", "confidence", "model")


@pytest.fixture
def blob_store():
    s = blobstore.MemoryBlobStore()
    app.dependency_overrides[blobstore.get_blob_store] = lambda: s
    yield s
    app.dependency_overrides.pop(blobstore.get_blob_store, None)


def _processed_drawing(db, project, dana):
    d = Document(project_id=project.id, filename="E-set.pdf", doc_type="Drawings", content_type="application/pdf",
                 size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id, status="processed", page_count=2)
    db.add(d); db.flush()
    for i, kind in enumerate(("plan", "schedule")):
        db.add(Sheet(project_id=project.id, number=f"E{i}", title="t", discipline="Electrical", revision="", scale="",
                     scale_options=[], plan="", takeoff_id=str(d.id), page_index=i, kind=kind))
    db.flush()
    return d


def test_upload_queues_a_read(client, db, project, signed_in_user, blob_store):
    res = client.post(f"/api/projects/{project.id}/documents", files={"file": ("E.pdf", b"%PDF-1.4\n", "application/pdf")}, data={"doc_type": "Drawings"})
    assert res.status_code == 201 and res.json()["status"] == "processing"
    assert db.scalars(select(Job).where(Job.kind == "read")).one().document_id == uuid.UUID(res.json()["id"])


def test_retyping_a_document_queues_a_read(client, db, project, dana, signed_in_user):
    d = _processed_drawing(db, project, dana)
    res = client.patch(f"/api/documents/{d.id}", json={"doc_type": "Specifications"})
    assert res.status_code == 200 and res.json()["status"] == "processing"
    assert db.scalars(select(Job).where(Job.kind == "read")).one().document_id == d.id


def test_retyping_a_document_is_refused_while_a_run_is_in_flight(client, db, project, dana, signed_in_user):
    d = _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    res = client.patch(f"/api/documents/{d.id}", json={"doc_type": "Specifications"})
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "run_in_flight"
    assert res.json()["detail"]["message"] == "Wait for the takeoff to finish before changing a document's type."
    db.refresh(d)
    assert d.doc_type == "Drawings"


def test_start_takeoff_queues_a_run_and_audits(client, db, project, dana, signed_in_user):
    _processed_drawing(db, project, dana)
    res = client.post(f"/api/projects/{project.id}/takeoff")
    assert res.status_code == 202 and set(res.json()) == {"run_id"}
    assert db.scalars(select(Job).where(Job.kind == "classify")).one().requested_by == dana.id
    assert db.scalars(select(Action).where(Action.kind == "takeoff_start")).one().label == "Started takeoff"
    assert client.post(f"/api/projects/{project.id}/takeoff").status_code == 409
    assert client.post(f"/api/projects/{project.id}/takeoff").json()["detail"]["code"] == "run_in_flight"


def test_start_takeoff_refuses_without_readable_drawings(client, db, project, signed_in_user):
    res = client.post(f"/api/projects/{project.id}/takeoff")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_readable_drawings"


def test_start_takeoff_refuses_while_a_drawing_set_is_still_being_read(client, db, project, dana, signed_in_user):
    """A set still reading would be left out of the run silently -- and
    its sheets would then show as waiting under a finished run."""
    _processed_drawing(db, project, dana)
    reading = Document(project_id=project.id, filename="E-addendum.pdf", doc_type="Drawings", content_type="application/pdf",
                       size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k2", uploaded_by=dana.id, status="processing")
    db.add(reading); db.flush()
    res = client.post(f"/api/projects/{project.id}/takeoff")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "drawings_still_reading"
    assert res.json()["detail"]["message"] == copy.DRAWINGS_READING
    assert db.scalars(select(Job).where(Job.kind == "classify")).all() == []
    # A specification still reading does not hold the run up: it is context, not sheets.
    reading.doc_type = "Specifications"; db.flush()
    assert client.post(f"/api/projects/{project.id}/takeoff").status_code == 202


def test_start_takeoff_refuses_during_the_sheet_phase(client, db, project, dana, signed_in_user):
    """"One run at a time" covers the whole run, not just its classify
    job: with classify done and a sheet job still open, a second Start
    is refused, so two runs never merge onto the same sheets."""
    _processed_drawing(db, project, dana)
    assert client.post(f"/api/projects/{project.id}/takeoff").status_code == 202
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    [sj] = queue.enqueue_sheets(db, c, [(plan, {})]); queue.mark_done(db, c); db.flush()
    res = client.post(f"/api/projects/{project.id}/takeoff")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "run_in_flight"
    sj.status = "done"; db.flush()
    assert client.post(f"/api/projects/{project.id}/takeoff").status_code == 202


def test_removing_a_document_is_refused_while_a_run_is_in_flight(client, db, project, dana, signed_in_user, blob_store):
    """Cascading a queued sheet job away with its sheet would leave the
    run with nobody to complete it. Refused during the sheet phase too,
    and allowed again once the run is done."""
    d = _processed_drawing(db, project, dana)
    assert client.post(f"/api/projects/{project.id}/takeoff").status_code == 202
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    [sj] = queue.enqueue_sheets(db, c, [(plan, {})]); queue.mark_done(db, c); db.flush()
    res = client.delete(f"/api/documents/{d.id}")
    assert res.status_code == 409 and res.json()["detail"] == {"code": "run_in_flight", "message": copy.REMOVE_DURING_RUN}
    assert db.get(Document, d.id) is not None
    assert db.scalars(select(Job).where(Job.id == sj.id)).one().status == "queued"
    sj.status = "done"; db.flush()
    assert client.delete(f"/api/documents/{d.id}").status_code == 204


def test_a_plan_sheet_read_after_the_run_started_needs_attention_not_waiting(client, db, project, dana, signed_in_user):
    """A drawing set whose read finished after classify queued its sheet
    jobs is not in the run. Its plan sheets say so, and the run is
    complete with failures rather than complete."""
    _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    [sj] = queue.enqueue_sheets(db, c, [(plan, {})]); queue.mark_done(db, c)
    late = Document(project_id=project.id, filename="E-late.pdf", doc_type="Drawings", content_type="application/pdf",
                    size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k3", uploaded_by=dana.id, status="processed", page_count=1)
    db.add(late); db.flush()
    db.add(Sheet(project_id=project.id, number="E3", title="late plan", discipline="Electrical", revision="", scale="",
                 scale_options=[], plan="", takeoff_id=str(late.id), page_index=0, kind="plan"))
    db.flush()
    run = client.get(f"/api/projects/{project.id}/processing").json()["run"]
    late_row = next(s for s in run["sheets"] if s["number"] == "E3")
    assert run["state"] == "running"
    assert late_row["stage"] == "attention" and late_row["reason"] == copy.SHEET_NOT_IN_RUN
    sj.status = "done"; db.flush()
    run = client.get(f"/api/projects/{project.id}/processing").json()["run"]
    assert run["state"] == "complete_with_failures" and run["complete_count"] == 2 and run["total_count"] == 3


def test_a_plan_sheet_with_no_job_under_a_queued_run_is_still_waiting(client, db, project, dana, signed_in_user):
    _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    run = client.get(f"/api/projects/{project.id}/processing").json()["run"]
    assert run["state"] == "queued"
    assert next(s for s in run["sheets"] if s["number"] == "E0")["stage"] == "waiting"


def test_processing_lists_each_read_drawing_sets_sheets_with_unreadable_ones_marked(client, db, project, dana, signed_in_user):
    """Screen D's sheet table (spec §8): number, title, kind label, and
    the reason a sheet is unreadable. A set still reading, and a
    specification, list none."""
    d = _processed_drawing(db, project, dana)
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    plan.unreadable_reason = "The sheet is a scanned image with no readable drawing content."
    reading = Document(project_id=project.id, filename="E-2.pdf", doc_type="Drawings", content_type="application/pdf",
                       size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k2", uploaded_by=dana.id, status="processing")
    spec = Document(project_id=project.id, filename="spec.pdf", doc_type="Specifications", content_type="application/pdf",
                    size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k4", uploaded_by=dana.id, status="processed")
    db.add_all([reading, spec]); db.flush()
    body = client.get(f"/api/projects/{project.id}/processing").json()
    by_name = {doc["filename"]: doc for doc in body["documents"]}
    sheets = by_name["E-set.pdf"]["sheets"]
    assert [s["number"] for s in sheets] == ["E0", "E1"]
    assert sheets[0] == {"id": str(plan.id), "number": "E0", "title": "t", "kind": "Electrical plan",
                         "unreadable_reason": "The sheet is a scanned image with no readable drawing content."}
    assert sheets[1]["kind"] == "Schedule" and sheets[1]["unreadable_reason"] == ""
    assert by_name["E-2.pdf"]["sheets"] == [] and by_name["spec.pdf"]["sheets"] == []
    text = json.dumps(body).lower()
    assert not any(w in text for w in FORBIDDEN), text


def test_processing_reports_documents_and_sheets_in_stage_words(client, db, project, dana, signed_in_user):
    d = _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    queue.enqueue_sheets(db, c, [(plan, {})]); queue.mark_done(db, c); db.flush()
    body = client.get(f"/api/projects/{project.id}/processing").json()
    [doc] = body["documents"]
    assert {k: v for k, v in doc.items() if k != "sheets"} == {"id": str(d.id), "filename": "E-set.pdf", "doc_type": "Drawings", "state": "read", "reason": "", "sheet_count": 2}
    run = body["run"]
    assert run["state"] == "running" and run["total_count"] == 2 and run["complete_count"] == 1
    stages = {s["number"]: s["stage"] for s in run["sheets"]}
    assert stages == {"E0": "waiting", "E1": "complete"}
    assert next(s for s in run["sheets"] if s["number"] == "E1")["note"] == "Schedule or legend — no devices counted."


def test_processing_counts_items_per_sheet_and_walks_the_sheet_job_stages(client, db, project, dana, signed_in_user):
    _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    [sj] = queue.enqueue_sheets(db, c, [(plan, {})]); queue.mark_done(db, c)
    for n in range(3):
        db.add(Item(project_id=project.id, sheet_id=plan.id, symbol="receptacle", name=f"Item {n}", system="Power",
                    category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY, x=1, y=1))
    db.flush()

    def plan_row():
        body = client.get(f"/api/projects/{project.id}/processing").json()
        return body["run"]["state"], next(s for s in body["run"]["sheets"] if s["number"] == "E0")

    sj.status, sj.progress = "running", ""; db.flush()
    state, row = plan_row()
    assert state == "running" and row["stage"] == "finding" and row["item_count"] == 3
    sj.progress = "checking"; db.flush()
    assert plan_row()[1]["stage"] == "checking"
    sj.status, sj.progress = "done", "unchecked"; db.flush()
    state, row = plan_row()
    assert state == "complete" and row["stage"] == "complete"
    assert row["note"] == "Schedules weren't checked on this sheet."
    sj.status, sj.error = "failed", "This sheet couldn't be processed. Start the takeoff again to retry it."; db.flush()
    state, row = plan_row()
    assert state == "complete_with_failures" and row["stage"] == "attention" and row["reason"] == sj.error


def test_processing_reports_a_failed_run_and_an_unreadable_sheet(client, db, project, dana, signed_in_user):
    _processed_drawing(db, project, dana)
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    plan.unreadable_reason = "This sheet couldn't be read."
    client.post(f"/api/projects/{project.id}/takeoff")
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    assert client.get(f"/api/projects/{project.id}/processing").json()["run"]["state"] == "queued"
    queue.mark_failed(db, c, "No drawings have been read yet. Upload a drawing set, or wait for reading to finish.")
    run = client.get(f"/api/projects/{project.id}/processing").json()["run"]
    assert run["state"] == "complete_with_failures" and run["reason"] == c.error
    row = next(s for s in run["sheets"] if s["number"] == "E0")
    assert row["stage"] == "attention" and row["reason"] == "This sheet couldn't be read."


def test_a_finished_run_of_only_unreadable_sheets_is_not_complete(client, db, project, dana, signed_in_user):
    """Seen live on a scanned set: every sheet unreadable at read time,
    so no sheet job at all, and the run reported `complete` with every
    row needing attention and none complete."""
    _processed_drawing(db, project, dana)
    for sheet in db.scalars(select(Sheet)).all():
        sheet.unreadable_reason = "The sheet is a scanned image with no readable drawing content."
    client.post(f"/api/projects/{project.id}/takeoff")
    c = db.scalars(select(Job).where(Job.kind == "classify")).one()
    queue.mark_done(db, c)
    run = client.get(f"/api/projects/{project.id}/processing").json()["run"]
    assert run["state"] == "complete_with_failures" and run["reason"] == ""
    assert run["complete_count"] == 0 and run["total_count"] == 2
    assert all(s["stage"] == "attention" for s in run["sheets"])


def test_processing_never_leaks_internals(client, db, project, dana, signed_in_user):
    _processed_drawing(db, project, dana)
    client.post(f"/api/projects/{project.id}/takeoff")
    text = json.dumps(client.get(f"/api/projects/{project.id}/processing").json()).lower()
    assert not any(w in text for w in FORBIDDEN), text


def test_processing_with_no_run_and_a_failed_document(client, db, project, dana, signed_in_user):
    d = Document(project_id=project.id, filename="bad.pdf", doc_type="Drawings", content_type="application/pdf", size_bytes=1,
                 sha256="b" * 64, storage_key="k", uploaded_by=dana.id, status="failed", error="Couldn't read this file.")
    db.add(d); db.flush()
    body = client.get(f"/api/projects/{project.id}/processing").json()
    assert body["run"] is None and body["documents"][0]["state"] == "failed" and body["documents"][0]["reason"] == "Couldn't read this file."


def test_processing_leaves_a_pricing_upload_out_of_the_document_list(client, db, project, dana, signed_in_user):
    """A price sheet never gets a read job, so its status stays
    `uploaded` -- which _DOC_STATE maps to "reading". Listed, it would
    be a drawing that never finishes reading, and screen E would poll
    for it forever."""
    _processed_drawing(db, project, dana)
    db.add(Document(project_id=project.id, filename="codale.xlsx", doc_type="Pricing",
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", size_bytes=1,
                    sha256="d" * 64, storage_key="k-price", uploaded_by=dana.id, status="uploaded"))
    db.flush()
    body = client.get(f"/api/projects/{project.id}/processing").json()
    assert [d["filename"] for d in body["documents"]] == ["E-set.pdf"]
    assert all(d["state"] != "reading" for d in body["documents"])


def test_deleting_a_document_cancels_its_read_and_removes_its_sheets(client, db, project, dana, signed_in_user, blob_store):
    d = _processed_drawing(db, project, dana)
    queue.enqueue_read(db, d); db.flush()
    assert client.delete(f"/api/documents/{d.id}").status_code == 204
    assert db.scalars(select(Job).where(Job.document_id == d.id)).all() == []
    assert db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).all() == []


def test_deleting_a_document_keeps_a_sheet_that_holds_an_approved_item(client, db, project, dana, signed_in_user, blob_store):
    """The same rule a re-read follows: a person's approval is never
    discarded by the engine or by document housekeeping. The approved
    item keeps its sheet, and the sheet says why nothing can update it."""
    d = _processed_drawing(db, project, dana)
    plan = db.scalars(select(Sheet).where(Sheet.kind == "plan")).one()
    approved = Item(project_id=project.id, sheet_id=plan.id, symbol="receptacle", name="Approved", system="Power",
                    category="Devices", quantity=1, unit="EA", status=ReviewStatus.APPROVED, x=1, y=1)
    unapproved = Item(project_id=project.id, sheet_id=plan.id, symbol="receptacle", name="Ready", system="Power",
                      category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY, x=2, y=2)
    db.add_all([approved, unapproved]); db.flush()
    assert client.delete(f"/api/documents/{d.id}").status_code == 204
    left = list(db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))))
    assert [s.id for s in left] == [plan.id] and left[0].unreadable_reason == "This page is no longer in the uploaded file."
    assert [i.id for i in db.scalars(select(Item).where(Item.sheet_id == plan.id))] == [approved.id]
