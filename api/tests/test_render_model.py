"""B3: the render job kind and the sheet columns behind the rendered
page (docs/superpowers/sdd/drawing-behind-the-markers). `render_status`
is a sheet property on its own axis, like `kind` -- never a review
label, and `render_key` never reaches the wire."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.jobs.schemas import JOB_KINDS, RENDER_STATUSES, timeout_for
from app.takeoff.models import Job, Sheet


def test_render_is_a_job_kind_with_its_own_timeout():
    assert "render" in JOB_KINDS
    assert timeout_for("render") == 300


def test_render_status_defaults_to_pending_and_is_closed(db, project, sheet):
    assert sheet.render_status == "pending" and sheet.render_key is None and sheet.max_zoom is None
    sheet.render_status = "drawn"
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()
    assert RENDER_STATUSES == ("pending", "rendered", "failed")


def test_a_render_job_row_is_accepted(db, project, sheet):
    db.add(Job(org_id=project.org_id, project_id=project.id, kind="render", sheet_id=sheet.id, status="queued"))
    db.flush()


def test_snapshot_carries_render_fields_and_never_the_key(client, db, project, sheet, signed_in_user):
    sheet.render_key = "orgs/x/projects/y/sheets/z/abcd/"
    sheet.render_status, sheet.max_zoom = "rendered", 3
    db.flush()
    body = client.get(f"/api/projects/{project.id}/snapshot").json()
    s = next(x for x in body["sheets"] if x["id"] == str(sheet.id))
    assert (s["render_status"], s["render_error"], s["max_zoom"]) == ("rendered", "", 3)
    assert "render_key" not in s and "orgs/" not in str(body)
