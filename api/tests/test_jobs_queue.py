"""The job queue's operations, shared by the API (enqueue) and the worker
(claim, finish). These tests commit deliberately: a second session has to
see the rows for the two-worker claim to mean anything, and the `db`
fixture's `drop_all` cleans up afterwards."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.jobs import copy, queue
from app.jobs.schemas import RETRY_BACKOFF_SECONDS, STALE_GRACE_SECONDS, timeout_for
from app.takeoff.models import Document, Sheet
from tests.conftest import TestSession


def _doc(db, project, dana, n="E.pdf"):
    d = Document(project_id=project.id, filename=n, doc_type="Drawings", content_type="application/pdf",
                 size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id)
    db.add(d); db.flush(); return d


def _past_stale(kind: str) -> timedelta:
    """One second past the point reclaim_stale gives up on a running job of `kind`."""
    return timedelta(seconds=timeout_for(kind) + STALE_GRACE_SECONDS + 1)


def _sheet(db, project, i=0):
    s = Sheet(project_id=project.id, number=f"E2.{i}", title="t", discipline="Electrical", revision="", scale="",
              scale_options=[], plan="", takeoff_id="d", page_index=i)
    db.add(s); db.flush(); return s


def test_enqueue_read_marks_the_document_processing_and_is_idempotent(db, project, dana):
    d = _doc(db, project, dana)
    j1 = queue.enqueue_read(db, d)
    j2 = queue.enqueue_read(db, d)
    assert j1.id == j2.id and d.status == "processing" and j1.kind == "read"


def test_enqueue_classify_refuses_a_second_run_in_flight(db, project, dana):
    queue.enqueue_classify(db, project, dana.id)
    with pytest.raises(Exception) as exc:
        queue.enqueue_classify(db, project, dana.id)
    assert getattr(exc.value, "code", "") == "run_in_flight"


def test_claim_is_fifo_and_a_sheet_waits_for_its_classify(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    s = _sheet(db, project)
    [sj] = queue.enqueue_sheets(db, c, [(s, {"clusters": []})])
    db.commit()
    first = queue.claim_next(db, "w1"); db.commit()
    assert first.id == c.id and first.status == "running" and first.attempts == 1
    assert queue.claim_next(db, "w1") is None          # the sheet job is not ready: classify not done
    queue.mark_done(db, first); db.commit()
    second = queue.claim_next(db, "w1"); db.commit()
    assert second.id == sj.id


def test_two_workers_never_claim_the_same_job(db, project, dana):
    for i in range(3):
        queue.enqueue_read(db, _doc(db, project, dana, f"{i}.pdf"))
    db.commit()
    a, b = TestSession(), TestSession()
    try:
        ja = queue.claim_next(a, "a")     # holds its row lock until commit
        jb = queue.claim_next(b, "b")     # SKIP LOCKED steps past it
        assert ja.id != jb.id
        a.commit(); b.commit()
    finally:
        a.close(); b.close()


def test_stale_running_jobs_are_reclaimed(db, project, dana):
    j = queue.enqueue_read(db, _doc(db, project, dana))
    db.commit()
    j = queue.claim_next(db, "dead"); db.commit()
    j.started_at = datetime.now(timezone.utc) - _past_stale("read")
    db.commit()
    assert queue.reclaim_stale(db) == []
    db.refresh(j)
    assert j.status == "queued" and j.attempts == 1 and j.locked_by == ""


def test_a_running_job_within_its_timeout_is_left_alone(db, project, dana):
    queue.enqueue_read(db, _doc(db, project, dana))
    db.commit()
    j = queue.claim_next(db, "alive"); db.commit()
    assert queue.reclaim_stale(db) == []
    db.refresh(j)
    assert j.status == "running" and j.locked_by == "alive"


def test_a_stale_job_out_of_attempts_fails_instead_of_requeueing(db, project, dana):
    d = _doc(db, project, dana)
    queue.enqueue_read(db, d)
    db.commit()
    j = queue.claim_next(db, "dead"); db.commit()
    j.attempts = j.max_attempts
    j.started_at = datetime.now(timezone.utc) - _past_stale("read")
    db.commit()
    assert queue.reclaim_stale(db) == []      # a read is no run's last sheet
    db.refresh(j)
    assert j.status == "failed" and j.error == copy.UNREADABLE
    assert d.status == "failed" and d.error == copy.UNREADABLE


def test_a_stale_sheet_job_out_of_attempts_fails_with_the_sheet_copy(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    [sj] = queue.enqueue_sheets(db, c, [(_sheet(db, project), {})])
    queue.mark_done(db, c); db.commit()
    sj = queue.claim_next(db, "dead"); db.commit()
    sj.attempts = sj.max_attempts
    sj.started_at = datetime.now(timezone.utc) - _past_stale("sheet")
    db.commit()
    assert queue.reclaim_stale(db) == [c.run_id]   # the run's only sheet: failing it completed the run
    db.refresh(sj)
    assert sj.status == "failed" and sj.error == copy.SHEET_FAILED


def test_requeue_backs_off_then_fails_after_max_attempts(db, project, dana):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    for _ in range(2):
        j = queue.claim_next(db, "w"); db.commit()
        queue.requeue(db, j, "Couldn't open this file right now."); db.commit()
        assert j.status == "queued" and j.not_before > datetime.now(timezone.utc) + timedelta(seconds=RETRY_BACKOFF_SECONDS - 5)
        j.not_before = None; db.commit()
    j = queue.claim_next(db, "w"); db.commit()
    queue.requeue(db, j, "Couldn't open this file right now."); db.commit()
    assert j.status == "failed" and d.status == "failed" and d.error == "Couldn't open this file right now."


def test_a_backed_off_job_is_not_claimable_until_not_before(db, project, dana):
    queue.enqueue_read(db, _doc(db, project, dana)); db.commit()
    j = queue.claim_next(db, "w"); db.commit()
    queue.requeue(db, j, "Couldn't open this file right now."); db.commit()
    assert queue.claim_next(db, "w") is None


def test_mark_failed_on_a_read_fails_the_document_with_the_copy(db, project, dana):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    j = queue.claim_next(db, "w"); db.commit()
    queue.mark_failed(db, j, "Couldn't read this file. Try re-saving it as PDF from the original and uploading again.")
    assert d.status == "failed" and d.error.startswith("Couldn't read this file.")


def test_a_run_completes_exactly_once_when_its_last_sheet_finishes(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    sheets = [_sheet(db, project, i) for i in range(2)]
    jobs = queue.enqueue_sheets(db, c, [(s, {}) for s in sheets])
    queue.mark_done(db, c); db.commit()
    jobs[0].status = "done"; db.commit()
    assert queue.complete_run_if_finished(db, c.run_id) is False
    jobs[1].status = "failed"; db.commit()
    assert queue.complete_run_if_finished(db, c.run_id) is True
    assert queue.complete_run_if_finished(db, c.run_id) is False   # already completed
    db.refresh(project)
    assert project.stage == "review"


def test_failing_the_last_sheet_job_completes_its_run(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    [sj] = queue.enqueue_sheets(db, c, [(_sheet(db, project), {})])
    queue.mark_done(db, c); db.commit()
    sj = queue.claim_next(db, "w"); db.commit()
    queue.mark_failed(db, sj, copy.SHEET_FAILED); db.commit()
    db.refresh(c)
    assert c.progress == "complete"
    assert queue.complete_run_if_finished(db, c.run_id) is False


def test_in_flight_run_covers_the_sheet_phase_not_just_classify(db, project, dana):
    """A run is in flight until its last sheet job is terminal. Before
    this, a second Start during the sheet phase queued run 2 while run
    1's sheets were still merging, and whichever finished last owned
    the pricing basis."""
    assert queue.in_flight_run(db, project.id) is None
    c = queue.enqueue_classify(db, project, dana.id)
    assert queue.in_flight_run(db, project.id).id == c.id
    jobs = queue.enqueue_sheets(db, c, [(_sheet(db, project, i), {}) for i in range(2)])
    queue.mark_done(db, c)
    assert queue.in_flight_run(db, project.id).id == c.id       # classify done, sheets open
    with pytest.raises(Exception) as exc:
        queue.enqueue_classify(db, project, dana.id)
    assert getattr(exc.value, "code", "") == "run_in_flight"
    jobs[0].status = "done"; db.flush()
    assert queue.in_flight_run(db, project.id).id == c.id       # one sheet still open
    jobs[1].status = "failed"; db.flush()
    assert queue.in_flight_run(db, project.id) is None          # every sheet terminal


def test_in_flight_run_is_none_once_a_run_with_no_sheets_is_done(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    queue.mark_done(db, c)
    assert queue.in_flight_run(db, project.id) is None


def test_a_stale_classify_job_out_of_attempts_fails_with_the_run_copy(db, project, dana):
    """The generic "re-save the file" is wrong for a classify job: the
    file was read fine, the run is what failed, and the recovery is to
    start it again."""
    queue.enqueue_classify(db, project, dana.id); db.commit()
    c = queue.claim_next(db, "dead"); db.commit()
    c.attempts = c.max_attempts
    c.started_at = datetime.now(timezone.utc) - _past_stale("classify")
    db.commit()
    assert queue.reclaim_stale(db) == []
    db.refresh(c)
    assert c.status == "failed" and c.error == copy.RUN_FAILED


def test_terminal_copy_substitutes_the_run_copy_for_a_classify_job_only_when_it_gave_no_reason(db, project, dana):
    c = queue.enqueue_classify(db, project, dana.id)
    assert queue.terminal_copy(c, "") == copy.RUN_FAILED
    assert queue.terminal_copy(c, copy.UNREADABLE) == copy.RUN_FAILED
    assert queue.terminal_copy(c, copy.NO_DRAWINGS) == copy.NO_DRAWINGS
