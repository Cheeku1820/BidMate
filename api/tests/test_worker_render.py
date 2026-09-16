"""The render job: every sheet a read detects gets its tile pyramid cut
and uploaded under a content-addressed prefix; a re-read of the same
bytes queues nothing; a failure marks one sheet and no other; removing a
document takes its queued renders with it."""
import io
import uuid

from sqlalchemy import func, select

from app.documents import blobstore
from app.jobs import copy, queue
from app.main import app
from app.takeoff.models import Job, Sheet
from app.worker import __main__ as worker
from tests.test_worker_read import _pdf, _run_all, _stored, inline  # noqa: F401


def _read(db, project, dana, store, monkeypatch, pages=2):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, store, _pdf("E2.1 POWER PLAN", pages=pages))
    queue.enqueue_read(db, d); _run_all(db)
    return d


def _render_jobs(db, status=None):
    where = [Job.kind == "render"] + ([Job.status == status] if status else [])
    return db.scalar(select(func.count()).select_from(Job).where(*where))


def test_read_queues_one_render_per_sheet_and_the_worker_renders_them(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    sheets = list(db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))))
    assert sheets and all(s.render_status == "rendered" and s.max_zoom is not None for s in sheets)
    s = sheets[0]
    assert s.render_key == f"orgs/{project.org_id}/projects/{project.id}/sheets/{s.id}/{d.sha256[:16]}/"
    assert inline.exists(s.render_key + "thumb.png") and inline.exists(s.render_key + "0/0_0.png")
    assert inline.exists(s.render_key + f"{s.max_zoom}/0_0.png")


def test_a_reread_of_the_same_bytes_queues_no_render(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    before = _render_jobs(db)
    queue.enqueue_read(db, d); _run_all(db)
    assert _render_jobs(db) == before


def test_a_reupload_with_new_bytes_renders_under_a_fresh_prefix(db, project, dana, inline, monkeypatch):
    d = _read(db, project, dana, inline, monkeypatch)
    s = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()
    old = s.render_key
    data = _pdf("E2.1 POWER PLAN  REV B", pages=2)
    d.sha256 = uuid.uuid4().hex * 2
    inline.put(d.storage_key, io.BytesIO(data), "application/pdf", len(data))
    queue.enqueue_read(db, d); _run_all(db)
    db.refresh(s)
    assert s.render_key != old and s.render_key.endswith(d.sha256[:16] + "/") and s.render_status == "rendered"


def test_a_failing_render_marks_only_its_sheet(db, project, dana, inline, monkeypatch):
    from app.engine import tiles
    real = tiles.render_sheet

    def flaky(path, page_index, out_dir):
        if page_index == 1:
            raise RuntimeError("boom")
        return real(path, page_index, out_dir)

    monkeypatch.setattr(tiles, "render_sheet", flaky)
    d = _read(db, project, dana, inline, monkeypatch)
    by_page = {s.page_index: s for s in db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id)))}
    assert by_page[1].render_status == "rendered"        # page_index is 1-based in the store
    assert by_page[2].render_status == "failed" and by_page[2].render_error == copy.RENDER_FAILED
    assert by_page[2].render_key is None


def test_a_transient_storage_error_on_upload_requeues_rather_than_failing(db, project, dana, inline, monkeypatch):
    """A storage blip on the way the tiles go *out* must retry like any
    other job -- not go straight to a terminal RENDER_FAILED the way it
    did before the download-side classification in blobs.storage_errors
    was reused for the upload loop too."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("E2.1 POWER PLAN", pages=1))
    queue.enqueue_read(db, d); db.commit()

    def flaky_put(key, stream, content_type, size):
        raise ConnectionError("storage down")

    monkeypatch.setattr(inline, "put", flaky_put)
    while worker.tick("t"):
        pass
    db.commit()

    render_job = db.scalars(select(Job).where(Job.kind == "render")).one()
    assert (render_job.status, render_job.attempts) == ("queued", 1)
    assert render_job.not_before is not None
    assert render_job.error == copy.UNAVAILABLE
    sheet = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).one()
    assert sheet.render_status == "pending"


def test_a_transient_storage_error_on_upload_fails_terminally_once_attempts_are_exhausted(db, project, dana, inline, monkeypatch):
    """Repeated retries eventually exhaust `max_attempts` and the sheet
    lands `failed`. The copy it fails with is the honest transient
    reason (`copy.UNAVAILABLE`), not `copy.RENDER_FAILED` -- because
    `queue.requeue`'s attempts-exhausted path hands its message straight
    to `mark_failed` without going through `terminal_copy` (unlike
    `reclaim_stale`'s), and `tests/test_jobs_queue.py::
    test_requeue_backs_off_then_fails_after_max_attempts` already pins
    that as deliberate: a job that kept failing for a known reason keeps
    that reason through to its terminal state instead of losing it to a
    generic label. This test is the render-kind instance of the same
    rule, not a gap in this fix -- what matters here is that the sheet
    reaches a genuinely terminal `failed` state at all, rather than
    retrying forever."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, inline, _pdf("E2.1 POWER PLAN", pages=1))
    queue.enqueue_read(db, d); db.commit()

    def flaky_put(key, stream, content_type, size):
        raise ConnectionError("storage down")

    monkeypatch.setattr(inline, "put", flaky_put)
    render_job = None
    # Run past the read, then force every retry's backoff so the render
    # job becomes claimable again without waiting real seconds.
    for _ in range(6):
        while worker.tick("t"):
            pass
        db.commit()
        render_job = db.scalars(select(Job).where(Job.kind == "render")).first()
        if render_job is None or render_job.status == "failed":
            break
        render_job.not_before = None
        db.commit()

    assert render_job.status == "failed" and render_job.attempts == render_job.max_attempts
    assert render_job.error == copy.UNAVAILABLE
    sheet = db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).one()
    assert sheet.render_status == "failed" and sheet.render_error == copy.UNAVAILABLE


def test_deleting_a_document_cancels_its_queued_renders(client, db, project, dana, inline, monkeypatch, signed_in_user):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    app.dependency_overrides[blobstore.get_blob_store] = lambda: inline   # the route's own blob delete
    try:
        d = _stored(db, project, dana, inline, _pdf("E2.1 POWER PLAN", pages=2))
        queue.enqueue_read(db, d); db.commit()
        worker.tick("t")                       # the read runs; renders are queued but not yet run
        db.commit()
        assert _render_jobs(db, "queued") >= 1
        assert client.delete(f"/api/documents/{d.id}").status_code == 204
        assert db.scalars(select(Job).where(Job.kind == "render")).all() == []
    finally:
        app.dependency_overrides.pop(blobstore.get_blob_store, None)
