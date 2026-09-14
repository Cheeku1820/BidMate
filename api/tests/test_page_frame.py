"""The frame transform is the fix under three of the spec's defects. These
tests pin the facts measured on 2026-09-14: raw text coordinates are
unrotated, page.rect is visual, and the transform round-trips."""

import pymupdf
import pytest

from app.engine import page_frame


@pytest.fixture
def rotated_page(tmp_path):
    """A 1000x800 page turned 90 degrees, so its visual frame is 800x1000.
    'A' is inserted at unrotated (100, 100); 'Z' at unrotated (900, 700)."""
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "A")
    page.insert_text((900, 700), "Z")
    page.set_rotation(90)
    path = tmp_path / "rot.pdf"
    doc.save(path)
    return pymupdf.open(path)[0]


def test_visual_words_land_inside_the_visual_page(rotated_page):
    assert rotated_page.rect.width == 800 and rotated_page.rect.height == 1000
    words = page_frame.visual_words(rotated_page)
    assert {w.text for w in words} == {"A", "Z"}
    for w in words:
        assert rotated_page.rect.contains(pymupdf.Rect(w.x0, w.y0, w.x1, w.y1)), w


def test_raw_words_would_not_have(rotated_page):
    """The bug: raw get_text coordinates do not fit the visual page."""
    raw = rotated_page.get_text("words")
    z = next(w for w in raw if w[4] == "Z")
    assert z[0] > rotated_page.rect.width, "raw x of Z exceeds the visual width"


def test_transform_round_trips(rotated_page):
    raw = rotated_page.get_text("words")
    r = pymupdf.Rect(raw[0][:4])
    back = page_frame.to_unrotated(page_frame.to_visual(r, rotated_page), rotated_page)
    assert abs(back.x0 - r.x0) < 1e-6 and abs(back.y1 - r.y1) < 1e-6


def test_visual_clip_reads_the_right_glyph(rotated_page):
    """A visual rect, derotated, is the clip get_textbox needs."""
    z = next(w for w in page_frame.visual_words(rotated_page) if w.text == "Z")
    clip = page_frame.to_unrotated(pymupdf.Rect(z.x0, z.y0, z.x1, z.y1), rotated_page)
    assert rotated_page.get_textbox(clip).strip() == "Z"


def test_visual_spans_match_visual_words(rotated_page):
    words = {w.text: (w.cx, w.cy) for w in page_frame.visual_words(rotated_page)}
    spans = page_frame.visual_spans(rotated_page)
    assert len(spans) == 2
    for cx, cy, font in spans:
        assert isinstance(font, str)
        assert any(abs(cx - wx) < 2 and abs(cy - wy) < 2 for wx, wy in words.values())


def test_unrotated_page_is_the_identity(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=1000, height=800)
    page.insert_text((100, 100), "A")
    raw = page.get_text("words")[0]
    w = page_frame.visual_words(page)[0]
    assert (round(w.x0), round(w.y0)) == (round(raw[0]), round(raw[1]))
