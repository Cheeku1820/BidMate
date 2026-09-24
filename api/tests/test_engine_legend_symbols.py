"""Legend rows and silhouettes (B3c spec §3). The legend is the only
labelled data a drawing set ships with; this reads it."""
import pymupdf
import pytest

from app.engine import glyphs
from app.engine import legend_symbols as ls
from app.engine.page_frame import visual_words
from tests.test_engine_glyphs import _receptacle


def _row(page, y, draw, text, modifier=""):
    draw(page, 120, y)
    if modifier:
        page.insert_text((132, y + 3), modifier, fontsize=5)
    page.insert_text((150, y + 3), text, fontsize=7)


@pytest.fixture
def legend():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)
    _row(page, 60, lambda p, x, y: _receptacle(p, x, y), "DUPLEX RECEPTACLE")
    _row(page, 100, lambda p, x, y: (_receptacle(p, x, y), p.draw_line((x - 6, y + 6), (x + 6, y - 6))), "GROUND FAULT RECEPTACLE")
    def money(p, x, y):
        s = p.new_shape(); s.draw_line((x, y - 6), (x, y + 6)); s.draw_circle((x, y - 2), 3); s.draw_circle((x, y + 2), 3)
        # A tick reaching toward the modifier column: the THREE-WAY row's
        # "3" is a touching subscript (MODIFIER_PT = 2.0 pt), and without
        # this the "money" glyph's own right edge sits 9 pt short of it --
        # never within reach, regardless of the module under test.
        s.draw_line((x, y), (x + 11, y))
        s.finish(color=(0, 0, 0), width=0.7); s.commit()
    _row(page, 140, money, "SINGLE POLE SWITCH")
    _row(page, 180, money, "THREE-WAY SWITCH", modifier="3")
    def boxed(p, x, y):
        s = p.new_shape(); s.draw_rect(pymupdf.Rect(x - 9, y - 9, x + 9, y + 9)); s.finish(color=(0, 0, 0), width=0.7); s.commit()
        s = p.new_shape(); s.draw_circle((x, y), 5); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    _row(page, 220, boxed, "RECESSED LIGHTING FIXTURE")
    # A stray drawing with no legend text beside it. A straight 60 pt line
    # is wider than glyphs.MAX_GLYPH_PT and would never become a candidate
    # at all -- that would test the glyph detector's size filter, not the
    # row rule this module owns. A small circle (curved => always
    # "shaped", so it qualifies as a glyph on its own) is a genuine
    # candidate with nothing beside it.
    s = page.new_shape(); s.draw_circle((150, 300), 3); s.finish(color=(0, 0, 0), width=0.7); s.commit()
    return page


def test_every_legend_row_becomes_a_template(legend):
    t = ls.templates_on(legend, visual_words(legend), sheet_number="E0.1")
    assert len(t) == 5
    assert [x.description for x in t][0] == "DUPLEX RECEPTACLE"
    assert all(x.sheet_number == "E0.1" for x in t)


def test_a_touching_subscript_is_the_modifier(legend):
    t = {x.description: x for x in ls.templates_on(legend, visual_words(legend))}
    assert t["THREE-WAY SWITCH"].modifier == "3"
    assert t["SINGLE POLE SWITCH"].modifier == ""
    assert "3" not in t["THREE-WAY SWITCH"].description


def test_a_composite_symbol_is_one_row(legend):
    t = [x for x in ls.templates_on(legend, visual_words(legend)) if "RECESSED" in x.description]
    assert len(t) == 1


def test_a_description_left_of_the_glyph_is_still_a_row():
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=200)
    page.insert_text((100, 63), "LEFT SIDE LABEL", fontsize=7)
    _receptacle(page, 300, 60)
    t = ls.templates_on(page, visual_words(page))
    assert len(t) == 1
    assert t[0].description == "LEFT SIDE LABEL"


def test_a_glyph_with_no_words_is_not_a_row(legend):
    words = visual_words(legend)
    region = (0, 0, legend.rect.width, legend.rect.height)
    all_glyphs = glyphs.glyphs_on(legend, region, words)
    # The stray circle is a real glyph candidate -- prove the row rule
    # rejects it (no description beside it), not that the glyph detector
    # never saw it in the first place.
    stray = min(all_glyphs, key=lambda g: abs((g.rect[0] + g.rect[2]) / 2 - 150)
                + abs((g.rect[1] + g.rect[3]) / 2 - 300))
    assert 144 <= stray.rect[0] and stray.rect[2] <= 156
    assert 294 <= stray.rect[1] and stray.rect[3] <= 306
    templates = ls.templates_on(legend, words)
    assert all(t.rect != stray.rect for t in templates)


def _scaled_receptacle(page, cx, cy, r):
    """The same drawn shape as _receptacle (test_engine_glyphs.py), but with
    stroke width and tail length proportional to r rather than _receptacle's
    fixed 0.5 pt / 2 pt (calibrated for its own default r=4.0). A silhouette
    is only "scale-free" against a true geometric scaling of one symbol --
    holding the stroke width and tail constant while the radius doubles
    draws a differently-proportioned symbol, not a bigger one, and ink
    fraction has no reason to match between the two."""
    width, tail = r * 0.125, r * 0.5
    s = page.new_shape()
    s.draw_circle((cx, cy), r)
    s.finish(color=(0, 0, 0), width=width)
    s.commit()
    s = page.new_shape()
    s.draw_line((cx - r - tail, cy), (cx - r, cy))
    s.draw_line((cx + r, cy), (cx + r + tail, cy))
    s.finish(color=(0, 0, 0), width=width)
    s.commit()


def test_silhouettes_are_fixed_size_and_scale_free():
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    _scaled_receptacle(page, 50, 50, r=4.0)
    _scaled_receptacle(page, 150, 50, r=8.0)
    words = visual_words(page)
    region = (0, 0, page.rect.width, page.rect.height)
    found = sorted(glyphs.glyphs_on(page, region, words), key=lambda g: g.rect[0])
    assert len(found) == 2
    small, large = found
    sil_small = ls.silhouette(page, small.rect)
    sil_large = ls.silhouette(page, large.rect)
    assert len(sil_small) == ls.SIL * ls.SIL
    assert len(sil_large) == ls.SIL * ls.SIL
    ink_small, ink_large = sum(sil_small), sum(sil_large)
    assert ink_small > 0 and ink_large > 0
    ratio = ink_small / ink_large
    assert 0.75 <= ratio <= 1.25


def test_sentence_case_keeps_short_acronyms():
    assert ls.sentence_case("DUPLEX RECEPTACLE") == "Duplex receptacle"
    assert ls.sentence_case("GFI RECEPTACLE") == "GFI receptacle"
    assert ls.sentence_case("") == ""


def _sil_of(page, description, words=None):
    t = {x.description: x for x in ls.templates_on(page, words or visual_words(page))}
    return t[description].silhouette


def test_a_glyph_scores_one_against_itself(legend):
    a = _sil_of(legend, "DUPLEX RECEPTACLE")
    assert ls.match_score(a, a) == pytest.approx(1.0, abs=1e-6)


def test_the_same_symbol_at_half_scale_ranks_first():
    # _receptacle's tail is a fixed 2 pt regardless of r, so r=8 and r=4
    # are not a true scaling of one shape (their aspect ratios differ --
    # 20x16 vs 12x8, the same fixture gap test_silhouettes_are_fixed_size
    # _and_scale_free already worked around with _scaled_receptacle).
    # Use that helper here too so this test exercises an actual half-scale
    # copy of the same symbol, not two different proportions.
    doc = pymupdf.open(); page = doc.new_page(width=400, height=200)
    _scaled_receptacle(page, 80, 80, r=8)      # the legend's size
    _scaled_receptacle(page, 240, 80, r=4)     # the plan's size
    words = visual_words(page)
    big, small = sorted(glyphs.glyphs_on(page, (0, 0, 400, 200), words), key=lambda g: g.rect[0])
    a, b = ls.silhouette(page, big.rect), ls.silhouette(page, small.rect)
    assert ls.match_score(a, b) >= 0.8


def test_a_rotated_copy_still_matches():
    doc = pymupdf.open(); page = doc.new_page(width=400, height=200)
    _receptacle(page, 80, 80, r=8)
    _receptacle(page, 240, 80, r=8, rot=90)
    words = visual_words(page)
    a, b = [ls.silhouette(page, g.rect) for g in sorted(glyphs.glyphs_on(page, (0, 0, 400, 200), words), key=lambda g: g.rect[0])]
    assert ls.match_score(a, b) >= 0.8


def test_ranking_is_ordered_capped_and_floored(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    sil = _sil_of(legend, "DUPLEX RECEPTACLE", words)
    ranked = ls.rank_templates(sil, "", templates)
    assert ranked and ranked[0].description == "DUPLEX RECEPTACLE"
    assert len(ranked) <= ls.MAX_SUGGESTIONS
    assert all(t.modifier == "" for t in ranked)
    assert ls.rank_templates(bytes(ls.SIL * ls.SIL), "", templates) == []


def test_a_modifier_selects_its_own_rows(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    sil = _sil_of(legend, "THREE-WAY SWITCH", words)
    ranked = ls.rank_templates(sil, "3", templates)
    assert [t.description for t in ranked] == ["THREE-WAY SWITCH"]


def test_near_identical_rows_both_survive(legend):
    words = visual_words(legend)
    templates = ls.templates_on(legend, words)
    ranked = ls.rank_templates(_sil_of(legend, "DUPLEX RECEPTACLE", words), "", templates)
    assert "GROUND FAULT RECEPTACLE" in [t.description for t in ranked]


def test_the_constants_are_what_the_corpus_set():
    assert (ls.SUGGESTION_FLOOR, ls.MAX_SUGGESTIONS, ls.SIL, ls.SPAN) == (0.30, 4, 32, 96)
