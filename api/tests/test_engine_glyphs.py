"""engine/glyphs.py: the shape rules the corpus set (B3b spec §3).
Every constant is a named value with a test; nothing here is tuned."""
import pymupdf
import pytest

from app.engine import glyphs
from app.engine.page_frame import visual_words


def _receptacle(page, cx, cy, rot=0, mirror=False, jitter=0.0, color=(0, 0, 0), r=4.0, perturb=0.0):
    """A circle with a bar through it, as electrical drafting draws a
    receptacle: two committed shapes -- the circle (one curved path) and
    the bar (its two line segments, sharing one committed shape, so one
    straight path). `perturb` nudges the y coordinate of the bar's far
    endpoint by that many points, to test TOL_PT's point-matching
    tolerance without translating the whole glyph."""
    m = pymupdf.Matrix(1, 1).prerotate(rot)
    if mirror:
        m = pymupdf.Matrix(-1, 1) * m
    def at(x, y):
        p = pymupdf.Point(x, y) * m
        return pymupdf.Point(p.x + cx + jitter, p.y + cy)
    s = page.new_shape()
    s.draw_circle(at(0, 0), r)
    s.finish(color=color, width=0.5)
    s.commit()
    s = page.new_shape()
    s.draw_line(at(-r - 2, 0), at(-r, 0))
    s.draw_line(at(r, 0), at(r + 2, perturb))
    s.finish(color=color, width=0.5)
    s.commit()


@pytest.fixture
def page():
    doc = pymupdf.open()
    return doc.new_page(width=1000, height=800)


def _region():
    return (20, 16, 820, 784)


def test_five_receptacles_in_four_orientations_form_one_cluster(page):
    _receptacle(page, 100, 100)
    _receptacle(page, 200, 100, rot=90)
    _receptacle(page, 300, 100, rot=180)
    _receptacle(page, 400, 100, mirror=True)
    _receptacle(page, 500, 100, jitter=0.1)
    g = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert len(g) == 5
    cl = glyphs.cluster(g)
    assert len(cl) == 1 and len(cl[0].members) == 5
    assert len(cl[0].signature) == 8


def test_screened_ink_is_never_a_glyph(page):
    _receptacle(page, 100, 100, color=(0.6, 0.6, 0.6))
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_a_dashed_wall_corner_is_not_a_glyph(page):
    s = page.new_shape()
    s.draw_line((100, 100), (100, 104)); s.draw_line((100, 104), (104, 104))
    s.finish(color=(0, 0, 0), width=0.5); s.commit()
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_three_straight_segments_are_a_glyph(page):
    s = page.new_shape()
    s.draw_line((100, 100), (106, 100)); s.finish(color=(0, 0, 0), width=0.5); s.commit()
    s = page.new_shape(); s.draw_line((100, 100), (100, 106)); s.finish(color=(0, 0, 0), width=0.5); s.commit()
    s = page.new_shape(); s.draw_line((100, 106), (106, 100)); s.finish(color=(0, 0, 0), width=0.5)
    s.commit()
    assert len(glyphs.glyphs_on(page, _region(), visual_words(page))) == 1


def test_a_hatch_and_a_large_box_are_not_glyphs(page):
    for i in range(30):   # > MAX_PATHS touching lines, each its own path
        s = page.new_shape()
        s.draw_line((100 + i * 0.3, 100), (100 + i * 0.3, 110))
        s.finish(color=(0, 0, 0), width=0.2)
        s.commit()
    # a filled circle among them makes the group pass the shape rule
    # (curved/closed/fill), so it's rejected only by MAX_PATHS
    s = page.new_shape(); s.draw_circle((104, 105), 1); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(300, 300, 360, 360)); s.finish(color=(0, 0, 0)); s.commit()
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_a_glyph_under_text_is_dropped(page):
    s = page.new_shape(); s.draw_rect(pymupdf.Rect(100, 100, 130, 112)); s.finish(color=(0, 0, 0)); s.commit()
    page.insert_text((104, 110), "111", fontsize=8)
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_fill_and_stroke_are_part_of_the_shape(page):
    s = page.new_shape(); s.draw_circle((100, 100), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    s = page.new_shape(); s.draw_circle((200, 100), 4); s.finish(color=(0, 0, 0)); s.commit()
    a, b = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert not glyphs.same_shape(a, b)


def test_outside_the_region_is_ignored(page):
    _receptacle(page, 900, 100)   # title-block strip
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_glyph_in_and_matches_of(page):
    for x in (100, 200, 300):
        _receptacle(page, x, 100)
    s = page.new_shape(); s.draw_circle((500, 100), 4); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    words = visual_words(page)
    found = glyphs.glyph_in(page, (90, 90, 112, 110), words)
    assert found is not None
    assert len(glyphs.matches_of(found, glyphs.glyphs_on(page, _region(), words))) == 3
    assert glyphs.glyph_in(page, (600, 600, 640, 640), words) is None


def test_signature_is_stable_and_orientation_free(page):
    _receptacle(page, 100, 100)
    _receptacle(page, 200, 100, rot=90)
    a, b = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert glyphs.signature_of(a) == glyphs.signature_of(b)


def test_tolerance_absorbs_small_jitter_and_rejects_large(page):
    _receptacle(page, 100, 100)
    _receptacle(page, 200, 100, perturb=0.2)   # within TOL_PT
    _receptacle(page, 300, 100, perturb=0.6)   # beyond TOL_PT
    a, b, c = glyphs.glyphs_on(page, _region(), visual_words(page))
    assert glyphs.same_shape(a, b)
    assert not glyphs.same_shape(a, c)


def test_a_candidate_under_min_glyph_pt_is_not_a_glyph(page):
    s = page.new_shape(); s.draw_circle((100, 100), 1); s.finish(color=(0, 0, 0), fill=(0, 0, 0)); s.commit()
    assert glyphs.glyphs_on(page, _region(), visual_words(page)) == []


def test_the_visual_frame_is_used_on_a_rotated_page():
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=1000)
    _receptacle(page, 100, 100)
    page.set_rotation(90)
    (g,) = glyphs.glyphs_on(page, (0, 0, 1000, 800), visual_words(page))
    x0, y0, x1, y1 = g.rect
    assert 0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 800
    # (100, 100) on the unrotated page lands near (900, 100) after a 90° turn
    assert abs((x0 + x1) / 2 - 900) < 8 and abs((y0 + y1) / 2 - 100) < 8
