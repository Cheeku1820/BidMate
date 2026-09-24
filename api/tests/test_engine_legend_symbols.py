"""Legend rows and silhouettes (B3c spec §3). The legend is the only
labelled data a drawing set ships with; this reads it."""
import pymupdf
import pytest

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
    s = page.new_shape(); s.draw_line((120, 300), (180, 300)); s.finish(color=(0, 0, 0), width=0.7); s.commit()  # no text
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


def test_a_glyph_with_no_words_is_not_a_row(legend):
    assert all("LINE" not in x.description for x in ls.templates_on(legend, visual_words(legend)))


def test_silhouettes_are_fixed_size_and_scale_free(legend):
    t = {x.description: x for x in ls.templates_on(legend, visual_words(legend))}
    a = t["DUPLEX RECEPTACLE"].silhouette
    assert len(a) == ls.SIL * ls.SIL
    assert any(b > 0 for b in a)


def test_sentence_case_keeps_short_acronyms():
    assert ls.sentence_case("DUPLEX RECEPTACLE") == "Duplex receptacle"
    assert ls.sentence_case("GFI RECEPTACLE") == "GFI receptacle"
    assert ls.sentence_case("") == ""
