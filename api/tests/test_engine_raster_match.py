"""Template matching on a page render (B3b spec §6, raster path)."""
import numpy as np
import pymupdf

from app.engine import raster_match
from tests.test_engine_glyphs import _receptacle


def _raster_pdf(tmp_path, spots, rot=0):
    """A vector page drawn, rendered to an image, and placed on a fresh
    page -- so the page has no vector paths, as a scanned sheet has none."""
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    for (x, y) in spots:
        _receptacle(p, x, y, rot=rot)
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open()
    page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "raster.pdf"
    out.save(path)
    return str(path)


def test_finds_every_copy_of_the_boxed_symbol(tmp_path):
    path = _raster_pdf(tmp_path, [(100, 100), (300, 100), (500, 400), (700, 600)])
    found = raster_match.find_on_render(path, 0, (92, 92, 108, 108))
    assert len(found) == 4
    centres = sorted(((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in found)
    for (cx, cy), (x, y) in zip(centres, sorted([(100, 100), (300, 100), (500, 400), (700, 600)])):
        assert abs(cx - x) < 2 and abs(cy - y) < 2


def test_rotated_copies_are_found(tmp_path):
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    _receptacle(p, 100, 100)
    _receptacle(p, 300, 100, rot=90)
    _receptacle(p, 500, 100, rot=180)
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open(); page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "rot.pdf"; out.save(path)
    assert len(raster_match.find_on_render(str(path), 0, (92, 92, 108, 108))) == 3


def test_a_different_symbol_is_not_a_match(tmp_path):
    src = pymupdf.open()
    p = src.new_page(width=1000, height=800)
    _receptacle(p, 100, 100)
    s = p.new_shape(); s.draw_rect(pymupdf.Rect(296, 96, 304, 104)); s.finish(color=(0, 0, 0)); s.commit()
    pix = p.get_pixmap(matrix=pymupdf.Matrix(3, 3))
    out = pymupdf.open(); page = out.new_page(width=1000, height=800)
    page.insert_image(page.rect, stream=pix.tobytes("png"))
    path = tmp_path / "diff.pdf"; out.save(path)
    found = raster_match.find_on_render(str(path), 0, (92, 92, 108, 108))
    assert len(found) == 1


def test_a_box_on_blank_paper_finds_nothing(tmp_path):
    """A near-uniform template (blank paper, an empty legend cell) must
    short-circuit on MIN_TEMPLATE_STD rather than search at all -- and
    must return promptly rather than hang the worker's sandboxed timeout."""
    path = _raster_pdf(tmp_path, [(100, 100)])
    found = raster_match.find_on_render(path, 0, (600, 600, 616, 616))
    assert found == []


def test_peaks_are_bounded(monkeypatch):
    monkeypatch.setattr(raster_match, "MAX_PEAKS", 10)
    score = np.ones((200, 200), dtype=np.float32)
    found = raster_match._peaks(score, tw=8, th=8)
    assert len(found) <= 10


def test_the_api_never_imports_opencv():
    import subprocess, sys, os
    code = "import sys; import app.main; assert 'cv2' not in sys.modules, 'app.main imported cv2'"
    r = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(os.path.dirname(__file__)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
