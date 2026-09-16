"""The loop around a job: claim, run, apply the outcome. Run inline so the
handler shares the test session, with a stub handler registered for the
job kind -- the real handlers arrive with the read, classify and sheet
jobs."""
import uuid

import pytest

from app.jobs import copy, queue
from app.takeoff.models import Document, Sheet
from app.worker import __main__ as worker
from app.worker import handlers, sandbox


@pytest.fixture
def inline(db, monkeypatch):
    monkeypatch.setenv("WORKER_INLINE", "1")
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)


@pytest.fixture
def handler(monkeypatch):
    """Registers a stub handler for `read` and returns a mutable holder
    the test sets the behaviour on."""
    calls = []
    behaviour = {"raise": None}

    def stub(db, job):
        calls.append(job.id)
        if behaviour["raise"] is not None:
            raise behaviour["raise"]

    # The real handlers first, so the stubs replace existing keys and
    # teardown puts the real ones back -- otherwise a mid-test import of
    # a handler module (worker._finish_run pulls in classify_job) would
    # re-register under a key monkeypatch then deletes, and every later
    # worker test would find no handler for that kind.
    handlers._load_handlers()
    monkeypatch.setitem(handlers.HANDLERS, "read", stub)
    monkeypatch.setitem(handlers.HANDLERS, "sheet", stub)
    monkeypatch.setitem(handlers.HANDLERS, "classify", stub)
    monkeypatch.setattr(handlers, "_load_handlers", lambda: None)
    behaviour["calls"] = calls
    return behaviour


def _doc(db, project, dana):
    d = Document(project_id=project.id, filename="E.pdf", doc_type="Drawings", content_type="application/pdf",
                 size_bytes=3, sha256=uuid.uuid4().hex * 2, storage_key="k", uploaded_by=dana.id)
    db.add(d); db.flush(); return d


def test_tick_with_nothing_queued_reports_no_work(db, inline):
    db.commit()
    assert worker.tick("t") is False


def test_tick_runs_the_handler_and_marks_the_job_done(db, project, dana, inline, handler):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    assert worker.tick("t") is True
    db.refresh(j)
    assert handler["calls"] == [j.id]
    assert j.status == "done" and j.error == "" and j.finished_at is not None


def test_a_transient_failure_requeues_with_its_copy(db, project, dana, inline, handler):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    handler["raise"] = sandbox.Transient("storage down")
    worker.tick("t")
    db.refresh(j)
    assert j.status == "queued" and j.error == "storage down" and j.not_before is not None


def test_a_terminal_failure_fails_the_job_and_its_document(db, project, dana, inline, handler):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    handler["raise"] = sandbox.Terminal(copy.ENCRYPTED)
    worker.tick("t")
    db.refresh(j); db.refresh(d)
    assert j.status == "failed" and j.error == copy.ENCRYPTED
    assert d.status == "failed" and d.error == copy.ENCRYPTED


def test_an_unexpected_exception_inline_is_terminal_with_the_generic_copy(db, project, dana, inline, handler):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    handler["raise"] = ZeroDivisionError("division by zero")
    worker.tick("t")
    db.refresh(j); db.refresh(d)
    assert j.status == "failed" and j.error == copy.UNREADABLE
    assert d.error == copy.UNREADABLE and "ZeroDivisionError" not in d.error


def test_a_sheet_job_that_raised_fails_with_the_sheet_copy(db, project, dana, inline, handler):
    c = queue.enqueue_classify(db, project, dana.id)
    s = Sheet(project_id=project.id, number="E2.1", title="t", discipline="Electrical", revision="", scale="",
              scale_options=[], plan="", takeoff_id="d", page_index=0)
    db.add(s); db.flush()
    [sj] = queue.enqueue_sheets(db, c, [(s, {})])
    queue.mark_done(db, c); db.commit()
    handler["raise"] = RuntimeError("vision pass exploded")
    worker.tick("t")
    db.refresh(sj); db.refresh(c); db.refresh(project)
    assert sj.status == "failed" and sj.error == copy.SHEET_FAILED
    assert c.progress == "complete" and project.stage == "review"   # the run still completes


def test_a_classify_job_that_raised_fails_with_the_run_copy(db, project, dana, inline, handler):
    """Not "re-save the file": the drawings were read fine. What failed
    is the run, and the recovery is to start it again."""
    c = queue.enqueue_classify(db, project, dana.id); db.commit()
    handler["raise"] = RuntimeError("classification exploded")
    worker.tick("t")
    db.refresh(c)
    assert c.status == "failed" and c.error == copy.RUN_FAILED


def test_a_classify_timeout_fails_with_the_run_copy(db, project, dana, inline, handler, monkeypatch):
    c = queue.enqueue_classify(db, project, dana.id); db.commit()
    monkeypatch.setattr(worker, "run_one", lambda job_id, kind: ("timeout", ""))
    worker.tick("t")
    db.refresh(c)
    assert c.status == "failed" and c.error == copy.RUN_FAILED


def test_a_classify_job_keeps_its_own_terminal_reason(db, project, dana, inline, handler):
    c = queue.enqueue_classify(db, project, dana.id); db.commit()
    handler["raise"] = sandbox.Terminal(copy.NO_DRAWINGS)
    worker.tick("t")
    db.refresh(c)
    assert c.status == "failed" and c.error == copy.NO_DRAWINGS


def test_a_timeout_outcome_fails_the_job_with_the_generic_copy(db, project, dana, inline, handler, monkeypatch):
    d = _doc(db, project, dana)
    j = queue.enqueue_read(db, d); db.commit()
    monkeypatch.setattr(worker, "run_one", lambda job_id, kind: ("timeout", ""))
    worker.tick("t")
    db.refresh(j)
    assert j.status == "failed" and j.error == copy.UNREADABLE


def test_run_refuses_a_kind_with_no_handler(db, project, dana, inline, monkeypatch):
    monkeypatch.setattr(handlers, "_load_handlers", lambda: None)
    monkeypatch.delitem(handlers.HANDLERS, "read", raising=False)
    j = queue.enqueue_read(db, _doc(db, project, dana)); db.commit()
    j = queue.claim_next(db, "t"); db.commit()
    with pytest.raises(sandbox.Terminal):
        handlers.run("read", str(j.id))


def test_run_ignores_a_job_that_is_not_running(db, project, dana, inline, handler):
    j = queue.enqueue_read(db, _doc(db, project, dana)); db.commit()
    handlers.run("read", str(j.id))            # still queued: not ours to run
    assert handler["calls"] == []
    assert handlers.run("read", str(uuid.uuid4())) is None


def test_the_loop_survives_a_tick_that_raises(db, project, dana, inline, handler, monkeypatch):
    """A database blip under claim_next must not take the worker down:
    the tick is logged, the loop polls again, and the next tick runs
    the job."""
    from sqlalchemy.exc import OperationalError

    j = queue.enqueue_read(db, _doc(db, project, dana)); db.commit()
    real_claim = queue.claim_next
    failures = {"left": 1}

    def flaky_claim(session, worker_id):
        if failures["left"]:
            failures["left"] -= 1
            raise OperationalError("SELECT 1", {}, ConnectionResetError("connection reset by peer"))
        return real_claim(session, worker_id)

    slept = []
    monkeypatch.setattr(queue, "claim_next", flaky_claim)
    monkeypatch.setattr(worker.time, "sleep", slept.append)
    worker.run_forever("t", max_ticks=2)
    db.refresh(j)
    assert j.status == "done" and handler["calls"] == [j.id]
    assert slept == [worker.POLL_SECONDS]   # the failed tick backed off; the successful one did not
