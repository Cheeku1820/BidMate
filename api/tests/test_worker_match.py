"""The match job: one drawn box in, every copy on the sheet out, in
sheet units; vector by shape, raster by render (B3b spec §6)."""
import pymupdf
from sqlalchemy import select

from app.jobs import copy, queue
from app.takeoff.models import Job, Sheet, SymbolMatch
from tests.test_engine_glyphs import _receptacle
from tests.test_worker_read import _run_all, _stored, inline  # noqa: F401


def _vector_pdf():
    doc = pymupdf.open()
    p = doc.new_page(width=1000, height=800)
    p.insert_text((72, 72), "E2.1 POWER PLAN")
    p.draw_rect(pymupdf.Rect(30, 30, 800, 760), color=(0, 0, 0))
    for x in (100, 300, 500):
        _receptacle(p, x, 400)
    s = p.new_shape(); s.draw_circle((700, 400), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    return doc.tobytes()


def _raster_pdf():
    src = pymupdf.open(stream=_vector_pdf(), filetype="pdf")
    pix = src[0].get_pixmap(matrix=pymupdf.Matrix(3, 3))
    doc = pymupdf.open()
    p = doc.new_page(width=1000, height=800)
    p.insert_image(p.rect, stream=pix.tobytes("png"))
    p.insert_text((72, 72), "E2.1 POWER PLAN")
    p.draw_rect(pymupdf.Rect(30, 30, 800, 760), color=(0, 0, 0))
    return doc.tobytes()


def _title_block_glyph_pdf():
    """A vector sheet whose only receptacle sits inside the title-block
    strip on the right edge -- outside the sheet's counting region,
    which the read job carves the located strip out of
    (documents._region). Every word is placed inside that same strip
    (x >= width * (1 - title_block.STRIP), i.e. the right ~18% of the
    page) so it is the strip `locate` finds."""
    doc = pymupdf.open()
    p = doc.new_page(width=1000, height=800)
    p.insert_text((850, 700), "E2.1 POWER PLAN")
    _receptacle(p, 850, 400)
    return doc.tobytes()


def _read(db, project, dana, store, monkeypatch, data):
    monkeypatch.setattr("app.db.SessionLocal", lambda: db)
    d = _stored(db, project, dana, store, data)
    queue.enqueue_read(db, d); _run_all(db)
    return db.scalars(select(Sheet).where(Sheet.takeoff_id == str(d.id))).first()


def _match(db, project, dana, sheet, box):
    m = SymbolMatch(org_id=project.org_id, project_id=project.id, sheet_id=sheet.id, box=box, created_by=dana.id)
    db.add(m); db.flush()
    queue.enqueue_match(db, m); _run_all(db)
    db.refresh(m)
    return m


def test_a_vector_sheet_matches_by_shape(db, project, dana, inline, monkeypatch):
    sheet = _read(db, project, dana, inline, monkeypatch, _vector_pdf())
    # the box around the first receptacle, in sheet units (1000x800 page -> x same, y * 750/800)
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "found" and len(m.matches) == 3
    xs = sorted(x for x, _y, _w, _h in m.matches)
    assert [abs(x - e) <= 2 for x, e in zip(xs, (100, 300, 500))] == [True] * 3
    assert all(w >= 1 and h >= 1 for _x, _y, w, h in m.matches)


def test_a_raster_sheet_matches_by_render(db, project, dana, inline, monkeypatch):
    sheet = _read(db, project, dana, inline, monkeypatch, _raster_pdf())
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "found" and len(m.matches) == 3


def test_a_boxed_glyph_outside_the_counting_region_is_still_a_match(db, project, dana, inline, monkeypatch):
    sheet = _read(db, project, dana, inline, monkeypatch, _title_block_glyph_pdf())
    m = _match(db, project, dana, sheet, [850, 375, 16, 15])
    assert m.status == "found" and len(m.matches) == 1


def test_find_matches_parses_the_page_once(monkeypatch, tmp_path):
    """Parsing the page's drawings is the expensive half of a dense sheet;
    the box lookup and the region search share one parse."""
    from app.engine import documents, glyphs
    from app.worker import match_job
    path = tmp_path / "e.pdf"; path.write_bytes(_vector_pdf())
    sheet = documents.detect_sheets(str(path))[0]
    real, calls = glyphs.paths_on, []
    monkeypatch.setattr(glyphs, "paths_on", lambda page: calls.append(1) or real(page))
    rects = match_job.find_matches(str(path), 0, sheet, (90, 390, 112, 410))
    assert len(rects) == 3 and len(calls) == 1


def test_a_failing_match_marks_its_row(db, project, dana, inline, monkeypatch):
    from app.worker import match_job
    sheet = _read(db, project, dana, inline, monkeypatch, _vector_pdf())
    monkeypatch.setattr(match_job, "find_matches", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    m = _match(db, project, dana, sheet, [100, 375, 16, 15])
    assert m.status == "failed" and m.error == copy.MATCH_FAILED
    job = db.scalars(select(Job).where(Job.symbol_match_id == m.id)).one()
    assert job.status == "failed" and "RuntimeError" not in job.error
