"""The processing response: stage words only (spec §7.1). Nothing here
serialises a job id, an attempt count, or a source -- ROADMAP invariant
7, and test_processing_api.py greps the body for the words that would
break it."""
from __future__ import annotations

from sqlalchemy import func, select

from app.jobs import copy
from app.takeoff.models import Document, Item, Job, Project, Sheet

_DOC_STATE = {"uploaded": "reading", "processing": "reading", "processed": "read", "failed": "failed"}
_TERMINAL = ("done", "failed")


def _sheet_stage(sheet: Sheet, job: Job | None) -> tuple[str, str, str]:
    """(stage, reason, note). A sheet unreadable at read time never gets
    a job, so it is `attention` with its own reason first; a non-plan
    sheet has nothing to count and is complete with a note saying so."""
    if sheet.unreadable_reason:
        return "attention", sheet.unreadable_reason, ""
    if sheet.kind != "plan":
        return "complete", "", copy.NON_PLAN
    if job is None or job.status == "queued":
        return "waiting", "", ""
    if job.status == "running":
        return ("checking" if job.progress == "checking" else "finding"), "", ""
    if job.status == "failed":
        return "attention", job.error, ""
    return "complete", "", (copy.SCHEDULES_UNCHECKED if job.progress == "unchecked" else "")


def _run_state(classify: Job, sheet_jobs: list[Job], rows: list[dict]) -> str:
    """A finished run is `complete` only when no listed sheet needs
    attention. A sheet unreadable at read time never gets a sheet job,
    so judging by jobs alone called a run of nothing but such sheets
    complete -- every row `attention`, none complete -- and "complete"
    over that list is silence reading as completeness."""
    if classify.status == "queued":
        return "queued"
    if classify.status == "failed":
        return "complete_with_failures"
    if classify.status == "running" or any(j.status not in _TERMINAL for j in sheet_jobs):
        return "running"
    failed = any(j.status == "failed" for j in sheet_jobs) or any(r["stage"] == "attention" for r in rows)
    return "complete_with_failures" if failed else "complete"


def build_processing(db, project: Project) -> dict:
    docs = list(db.scalars(select(Document).where(Document.project_id == project.id).order_by(Document.created_at, Document.id)))
    sheets = list(db.scalars(select(Sheet).where(Sheet.project_id == project.id).order_by(Sheet.sort_order, Sheet.page_index)))
    sheets_per_doc: dict[str, int] = {}
    for s in sheets:
        sheets_per_doc[s.takeoff_id] = sheets_per_doc.get(s.takeoff_id, 0) + 1
    documents = [{"id": str(d.id), "filename": d.filename, "doc_type": d.doc_type,
                  "state": _DOC_STATE.get(d.status, "reading"),
                  "reason": d.error if d.status == "failed" else "",
                  "sheet_count": sheets_per_doc.get(str(d.id), 0)} for d in docs]

    classify = db.scalars(select(Job).where(Job.project_id == project.id, Job.kind == "classify")
                          .order_by(Job.queued_at.desc())).first()
    if classify is None:
        return {"documents": documents, "run": None}

    sheet_jobs = list(db.scalars(select(Job).where(Job.run_id == classify.run_id, Job.kind == "sheet")))
    job_by_sheet = {j.sheet_id: j for j in sheet_jobs}
    # Only sheets from a drawing set the worker has read: a sheet row
    # from a document since retyped or still being re-read is not part
    # of this run.
    read_drawings = {str(d.id) for d in docs if d.status == "processed" and d.doc_type == "Drawings"}
    listed = [s for s in sheets if s.takeoff_id in read_drawings]
    item_counts = dict(db.execute(
        select(Item.sheet_id, func.count()).where(Item.sheet_id.in_([s.id for s in listed])).group_by(Item.sheet_id)
    ).all()) if listed else {}
    rows = []
    for s in listed:
        stage, reason, note = _sheet_stage(s, job_by_sheet.get(s.id))
        rows.append({"id": str(s.id), "number": s.number, "title": s.title, "stage": stage, "reason": reason,
                     "note": note, "item_count": int(item_counts.get(s.id, 0))})
    return {"documents": documents,
            "run": {"state": _run_state(classify, sheet_jobs, rows),
                    "reason": classify.error if classify.status == "failed" else "",
                    "sheets": rows,
                    "complete_count": sum(1 for r in rows if r["stage"] == "complete"),
                    "total_count": len(rows)}}
