"""The classify and sheet handlers: orchestration, with a fake engine.
Counting, classification and the per-sheet finish are stubbed so these
tests assert what the worker does *around* the engine -- what it counts,
how often it classifies, what it queues, what it writes -- and never how
a drawing is read. The PDF is test_worker_read's two-page drawing."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.engine import classification as cls_mod, counting, sheet as sheet_mod
from app.engine.contracts import Classification, DeviceCluster, Placement, SheetResult
from app.jobs import copy, queue
from app.jobs.schemas import STALE_GRACE_SECONDS, timeout_for
from app.takeoff.models import Action, Classification as ClassificationRow, Item, Job, Note, Sheet
from app.worker import __main__ as worker, handlers
from tests.test_worker_read import _pdf, _run_all, _stored, inline  # noqa: F401


def _row(tag, x, y, page):
    return {"name": f"Item {tag}", "system": "Power", "category": "Devices", "unit": "ea", "quantity": 1, "status": "ready",
            "sheet_id": str(page), "page": page + 1, "symbol": "receptacle", "warning": None, "x": x, "y": y,
            "placements": [[x, y]], "tag": tag, "material_cost": 1.0, "labor_hours": 1.0, "labor_cost": 78.0, "total_cost": 79.0}


@pytest.fixture
def fake_engine(monkeypatch):
    calls = {"classify": [], "finish": []}
    monkeypatch.setattr(counting, "count_sheet", lambda path, sheet: [DeviceCluster("R", sheet.page_index, [Placement(300, 300)])])

    def classify_run(clusters, sheets, schedule_text, context, notes, location):
        calls["classify"].append({"tags": sorted(c.tag for c in clusters), "context": context, "notes": notes})
        return Classification(specs_by_tag={"R": {"name": "20A duplex receptacle", "confidence": "high", "material_cost": 5, "labor_hours": 0.5}},
                              labor_rate=80.0, material_factor=1.1, source="llm", location_note="note")
    monkeypatch.setattr(cls_mod, "classify_run", classify_run)

    def finish(path, sheet, clusters, classification, sheets):
        calls["finish"].append(sheet.page_index)
        return SheetResult(rows=[_row(c.tag, p.x, p.y, sheet.page_index) for c in clusters for p in c.placements], ai_reading=None)
    monkeypatch.setattr(sheet_mod, "finish", finish)
    return calls


def _seeded(db, project, dana, store, monkeypatch, pages=2):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, store, _pdf("E2.1 POWER PLAN", pages=pages))
    queue.enqueue_read(db, d); _run_all(db)
    return d


def _sheets_by_page(db, project) -> dict[int, Sheet]:
    """The project's sheets keyed by the engine's 0-based page index.
    `Sheet.page_index` itself is 1-based -- the read job stores the
    engine payload's `page` -- which is the same conversion the worker
    makes on the way back into the engine."""
    return {s.page_index - 1: s for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}


def test_a_run_counts_every_plan_sheet_classifies_once_and_writes_per_sheet(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    assert len(fake_engine["classify"]) == 1 and fake_engine["classify"][0]["tags"] == ["R", "R"]
    assert sorted(fake_engine["finish"]) == [0, 1]
    items = list(db.scalars(select(Item).where(Item.project_id == project.id)))
    assert len(items) == 2 and {i.name for i in items} == {"Item R"}
    assert db.scalars(select(ClassificationRow)).one().source == "llm"
    db.refresh(project)
    assert project.stage == "review" and project.pricing_source == "llm"
    ingest = db.scalars(select(Action).where(Action.kind == "ingest")).one()
    assert ingest.actor_user_id == dana.id and ingest.label == "Processed 2 sheet(s) into 2 item(s)"
    assert all(j.status == "done" for j in db.scalars(select(Job)))
    # No vision reading on the model path: screen E says the schedules weren't checked.
    assert {j.progress for j in db.scalars(select(Job).where(Job.kind == "sheet"))} == {"unchecked"}


def test_each_sheet_job_carries_its_own_clusters_and_lands_on_its_own_sheet(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    sheets = _sheets_by_page(db, project)
    jobs = {j.sheet_id: j for j in db.scalars(select(Job).where(Job.kind == "sheet"))}
    assert set(jobs) == {sheets[0].id, sheets[1].id}
    assert all(j.payload["clusters"] == [{"tag": "R", "placements": [[300, 300]]}] for j in jobs.values())
    for page, sheet in sheets.items():
        [item] = db.scalars(select(Item).where(Item.sheet_id == sheet.id))
        assert item.source_tag == "R" and item.evidence["sheet"] == "E2.1"


def test_context_notes_reach_the_classifier_and_are_stamped_applied(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)
    db.add(Note(project_id=project.id, title="Ceiling", body="14 ft", category="existing_condition", usage="context", author_user_id=dana.id))
    db.add(Note(project_id=project.id, title="Ref", body="ignore", category="existing_condition", usage="reference", author_user_id=dana.id))
    db.flush()
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    [call] = fake_engine["classify"]
    assert [n["title"] for n in call["notes"]] == ["Ceiling"]
    applied = [n for n in db.scalars(select(Note)) if n.applied_at is not None]
    assert [n.title for n in applied] == ["Ceiling"]


def test_scope_statements_feed_context_unless_dismissed(db, project, dana, inline, monkeypatch, fake_engine):
    from app.takeoff.models import ScopeStatement
    d = _seeded(db, project, dana, inline, monkeypatch)
    db.add_all([
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="excluded", text="Site lighting excluded.", quote="q", status="found", run_id=d.id),
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="included", text="Confirmed thing.", quote="q", status="confirmed", edited_text="Confirmed thing, edited.", run_id=d.id),
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="excluded", text="Dismissed thing.", quote="q", status="dismissed", run_id=d.id),
    ]); db.flush()
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    ctx = fake_engine["classify"][0]["context"]
    assert "Site lighting excluded." in ctx and "Confirmed thing, edited." in ctx and "Dismissed thing." not in ctx


def test_scope_statements_survive_a_specification_that_fills_the_context_cap(db, project, dana, inline, monkeypatch, fake_engine):
    """One full-length specification is already the whole cap. The scope
    block goes first, so it is the document text that gets cut, never
    the statements a person confirmed."""
    from app.engine.context import CONTEXT_CAP
    from app.takeoff.models import Document, ScopeStatement
    d = _seeded(db, project, dana, inline, monkeypatch)
    spec = Document(project_id=project.id, filename="spec.pdf", doc_type="Specifications", content_type="application/pdf",
                    size_bytes=1, sha256="a" * 64, storage_key="k/spec", uploaded_by=dana.id, status="processed",
                    context_text="x" * CONTEXT_CAP)
    db.add(spec)
    db.add_all([
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="excluded", text="Site lighting excluded.", quote="q", status="found", run_id=d.id),
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="included", text="Confirmed thing.", quote="q", status="confirmed", edited_text="Confirmed thing, edited.", run_id=d.id),
        ScopeStatement(org_id=project.org_id, project_id=project.id, document_id=d.id, page_index=0, kind="excluded", text="Dismissed thing.", quote="q", status="dismissed", run_id=d.id),
    ]); db.flush()
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    ctx = fake_engine["classify"][0]["context"]
    assert len(ctx) == CONTEXT_CAP
    assert "Site lighting excluded." in ctx and "Confirmed thing, edited." in ctx and "Dismissed thing." not in ctx
    assert ctx.index("[scope statements") < ctx.index("[spec.pdf]")


def test_other_documents_context_text_reaches_the_classifier(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)
    spec = _stored(db, project, dana, inline, _pdf("DIVISION 26 ELECTRICAL\nPanelboards shall be 42 circuit.\n"), doc_type="Specifications", name="spec.pdf")
    queue.enqueue_read(db, spec); _run_all(db)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    ctx = fake_engine["classify"][0]["context"]
    assert "[spec.pdf]" in ctx and "42 circuit" in ctx


def test_a_sheet_that_cannot_be_counted_is_marked_unreadable_and_the_run_continues(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)

    def count_sheet(path, sheet):
        if sheet.page_index == 1:
            raise RuntimeError("bad page")
        return [DeviceCluster("R", 0, [Placement(300, 300)])]
    monkeypatch.setattr(counting, "count_sheet", count_sheet)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    sheets = _sheets_by_page(db, project)
    assert sheets[1].unreadable_reason == "This sheet couldn't be read." and sheets[0].unreadable_reason == ""
    assert fake_engine["finish"] == [0]
    assert [j.sheet_id for j in db.scalars(select(Job).where(Job.kind == "sheet"))] == [sheets[0].id]
    db.refresh(project); assert project.stage == "review"


def test_the_engine_is_handed_zero_based_pages(db, project, dana, inline, monkeypatch, fake_engine):
    """`Sheet.page_index` is stored 1-based; the engine opens pages
    0-based. A marker counted on the wrong page is the one visibly
    wrong marker that costs trust in every other -- so the bridge is
    pinned here."""
    _seeded(db, project, dana, inline, monkeypatch)
    seen = []
    monkeypatch.setattr(counting, "count_sheet", lambda path, sheet: seen.append(sheet.page_index) or [])
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    assert sorted(seen) == [0, 1]


def test_a_failed_sheet_job_leaves_its_siblings_complete(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)

    def finish(path, sheet, clusters, classification, sheets):
        if sheet.page_index == 1:
            raise RuntimeError("crop exploded")
        return SheetResult(rows=[_row("R", 300, 300, 0)], ai_reading=None)
    monkeypatch.setattr(sheet_mod, "finish", finish)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    jobs = {j.sheet_id: j for j in db.scalars(select(Job).where(Job.kind == "sheet"))}
    sheets = _sheets_by_page(db, project)
    assert jobs[sheets[0].id].status == "done" and jobs[sheets[1].id].status == "failed"
    assert jobs[sheets[1].id].error == "This sheet couldn't be processed. Start the takeoff again to retry it."
    db.refresh(project); assert project.stage == "review"


def test_a_run_whose_last_sheet_job_fails_still_gets_its_pricing_basis(db, project, dana, inline, monkeypatch, fake_engine):
    """The run completes from the parent's failure path, not from a sheet
    handler, so the project writes that normally ride on the last sheet
    job have to be made there too."""
    _seeded(db, project, dana, inline, monkeypatch)
    order = []

    def finish(path, sheet, clusters, classification, sheets):
        order.append(sheet.page_index)
        if len(order) == 2:                       # whichever sheet runs last
            raise RuntimeError("crop exploded")
        return SheetResult(rows=[_row("R", 300, 300, sheet.page_index)], ai_reading=None, assembly_applied=True)
    monkeypatch.setattr(sheet_mod, "finish", finish)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    assert sorted(j.status for j in db.scalars(select(Job).where(Job.kind == "sheet"))) == ["done", "failed"]
    db.refresh(project)
    assert project.stage == "review" and project.pricing_source == "llm"
    assert "Branch wiring is estimated at" in project.pricing_note
    ingest = db.scalars(select(Action).where(Action.kind == "ingest")).one()
    assert ingest.label == "Processed 1 sheet(s) into 1 item(s)"   # the failed sheet was not processed


def test_a_stale_exhausted_last_sheet_job_reclaimed_by_a_tick_still_finishes_the_run(db, project, dana, inline, monkeypatch, fake_engine):
    """The worker that held the run's last sheet died with it, and the job
    is out of attempts: the next tick's reclaim fails it and completes
    the run, and the project writes are made from that tick."""
    _seeded(db, project, dana, inline, monkeypatch)
    queue.enqueue_classify(db, project, dana.id); db.commit()
    assert worker.tick("t")                       # classify: two sheet jobs queued
    assert worker.tick("t")                       # the first sheet, done
    dead = queue.claim_next(db, "dead"); db.commit()
    assert dead.kind == "sheet"
    dead.attempts = dead.max_attempts
    dead.started_at = datetime.now(timezone.utc) - timedelta(seconds=timeout_for("sheet") + STALE_GRACE_SECONDS + 1)
    db.commit()
    worker.tick("t")                              # nothing to claim; reclaim fails the stale job
    db.refresh(dead)
    assert dead.status == "failed" and dead.error == copy.SHEET_FAILED
    db.refresh(project)
    assert project.stage == "review" and project.pricing_source == "llm" and project.pricing_note.startswith("note")
    assert db.scalars(select(Action).where(Action.kind == "ingest")).one().label == "Processed 1 sheet(s) into 1 item(s)"


def test_the_basis_note_folds_every_sheets_assembly_and_unmatched_result(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)

    def finish(path, sheet, clusters, classification, sheets):
        applied, bare = (True, set()) if sheet.page_index == 0 else (False, {"Widget"})
        return SheetResult(rows=[_row("R", 300, 300, sheet.page_index)], ai_reading=None, assembly_applied=applied, bare_names=bare)
    monkeypatch.setattr(sheet_mod, "finish", finish)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    row = db.scalars(select(ClassificationRow)).one()
    assert row.wiring_note.startswith("Branch wiring is estimated at") and "Widget" in row.unmatched_note
    db.refresh(project)
    assert project.pricing_note == " ".join(["note", row.wiring_note, row.unmatched_note])


def test_the_deterministic_path_hands_each_sheet_the_tags_the_run_classified(db, project, dana, inline, monkeypatch, fake_engine):
    _seeded(db, project, dana, inline, monkeypatch)
    monkeypatch.setattr(cls_mod, "classify_run", lambda *a: Classification(
        specs_by_tag={}, labor_rate=70.0, material_factor=1.0, source="deterministic", location_note="regional",
        classified_tags={"R"}))
    handed = []

    def finish(path, sheet, clusters, classification, sheets):
        handed.append(classification)
        return SheetResult(rows=[], ai_reading=None)
    monkeypatch.setattr(sheet_mod, "finish", finish)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    assert len(handed) == 2
    assert all(c.source == "deterministic" and c.classified_tags == {"R"} and c.specs_by_tag == {} for c in handed)
    assert all(c.labor_rate == 70.0 and c.material_factor == 1.0 for c in handed)
    db.refresh(project)
    assert project.pricing_source == "deterministic"
    assert {j.progress for j in db.scalars(select(Job).where(Job.kind == "sheet"))} == {""}


def test_a_classify_job_run_twice_for_one_run_classifies_once_and_keeps_one_sheet_set(db, project, dana, inline, monkeypatch, fake_engine):
    """A reclaimed job can be re-run after its first attempt committed
    (the row and the sheet jobs land together). The second run finds the
    row, spends no model call, queues nothing, and the run still
    finishes."""
    _seeded(db, project, dana, inline, monkeypatch)
    c = queue.enqueue_classify(db, project, dana.id); db.commit()
    assert worker.tick("t")                       # first attempt: row + two sheet jobs committed
    c.status, c.progress, c.locked_by = "running", "", "again"   # re-claimed, as after a reclaim
    db.commit()
    handlers.run("classify", str(c.id))
    assert len(fake_engine["classify"]) == 1
    assert len(list(db.scalars(select(ClassificationRow).where(ClassificationRow.run_id == c.run_id)))) == 1
    assert len(list(db.scalars(select(Job).where(Job.kind == "sheet", Job.run_id == c.run_id)))) == 2
    db.refresh(c); assert c.status == "done"
    _run_all(db)
    db.refresh(project); assert project.stage == "review" and project.pricing_source == "llm"


def test_a_project_with_no_plan_sheets_completes_its_run_at_once(db, project, dana, inline, monkeypatch, fake_engine):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("LUMINAIRE SCHEDULE\nTYPE A  2x4 LED TROFFER\nTYPE B  DOWNLIGHT\n"))
    queue.enqueue_read(db, d); _run_all(db)
    for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id)):
        s.kind = "schedule"
    db.commit()
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    assert fake_engine["classify"][0]["tags"] == []
    assert list(db.scalars(select(Job).where(Job.kind == "sheet"))) == []
    db.refresh(project)
    assert project.stage == "review" and project.pricing_source == "llm"
    assert db.scalars(select(Action).where(Action.kind == "ingest")).one().label == "Processed 0 sheet(s) into 0 item(s)"


def _tagged_drawing() -> bytes:
    """Two plan pages; only the second carries device tags, so the
    engine's own counting has to open the right page to find them."""
    import pymupdf
    doc = pymupdf.open()
    for page_no in range(2):
        p = doc.new_page(width=1224, height=792)
        p.insert_text((72, 72), "E2.1 POWER PLAN")
        p.draw_rect(pymupdf.Rect(100, 100, 900, 700))
        if page_no == 1:
            for i in range(4):
                p.insert_text((200 + i * 120, 400), "R", fontname="helv")
    return doc.tobytes()


def test_the_real_engine_counts_the_page_the_sheet_row_points_at(db, project, dana, inline, monkeypatch):
    """No fakes: counting, classification (deterministic, no key) and the
    per-sheet finish run for real, so the 1-based row / 0-based engine
    bridge and the evidence crop are exercised against actual pages."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    d = _stored(db, project, dana, inline, _tagged_drawing())
    queue.enqueue_read(db, d); _run_all(db)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    sheets = _sheets_by_page(db, project)
    items = list(db.scalars(select(Item).where(Item.project_id == project.id)))
    assert [i.sheet_id for i in items] == [sheets[1].id] and items[0].quantity == 4 and items[0].source_tag == "R"
    assert items[0].evidence["has_image"] is True
    assert {j.status for j in db.scalars(select(Job))} == {"done"}
    db.refresh(project)
    assert project.stage == "review" and project.pricing_source == "deterministic"


def test_a_project_with_no_readable_drawings_fails_the_run_with_copy(db, project, dana, inline, monkeypatch, fake_engine):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    queue.enqueue_classify(db, project, dana.id); _run_all(db)
    j = db.scalars(select(Job).where(Job.kind == "classify")).one()
    assert j.status == "failed" and j.error.startswith("No drawings have been read yet.")
    assert j.error == copy.NO_DRAWINGS
    db.refresh(project); assert project.stage != "review"
