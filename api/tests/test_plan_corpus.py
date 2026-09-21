"""What the plan says about the real bid sets. Both raster sets produce
nothing but the scanned question; a vector set produces schedules; a set
with a specification produces Division 26 sections. Runs the engine's
read in-process, as test_corpus_sheets.py does, then feeds the stored
shapes into the plan's derivation."""

import os

import pytest

from app.plan.detect import DocIn, SheetIn, phases, questions, schedules, spec_sections
from tests.bid_set import RASTER_SETS, VECTOR_SETS, corpus_path


def _read(rel, doc_type):
    path = corpus_path(rel)
    if not os.path.exists(path):
        pytest.skip(f"corpus set not present: {rel}")
    from app.engine import documents
    reading = documents.read(path, doc_type)
    doc = DocIn(id="d", filename=os.path.basename(path), doc_type=doc_type, status="processed",
                context_text=reading.context_text, page_count=reading.page_count)
    sheets = [SheetIn(id=f"s{s.page_index}", document_id="d", number=s.number, title=s.title, kind=s.kind,
                      page_index=s.page_index, scale=s.scale, scale_options=(), unreadable_reason=s.unreadable_reason,
                      schedule_text=s.schedule_text) for s in reading.sheets]
    return doc, sheets, reading


@pytest.mark.parametrize("name", sorted(RASTER_SETS))
def test_a_scanned_set_is_one_question_and_nothing_else(name):
    doc, sheets, reading = _read(RASTER_SETS[name], "Drawings")
    assert schedules(sheets, [doc]) == [] and phases(sheets, [doc]) == []
    qs = questions(sheets, [doc], scope_count=len(reading.scope), phase_count=0, schedule_count=0)
    assert [q.rule for q in qs] == ["scanned", "no_specs", "no_scope"]
    assert qs[0].found.startswith(f"{len(sheets)} of {reading.page_count} pages")


def test_unalaska_has_a_schedule_and_no_scanned_question():
    doc, sheets, _ = _read(VECTOR_SETS["unalaska"], "Drawings")
    assert schedules(sheets, [doc]), "the Unalaska set carries luminaire and panel schedules"
    assert not [q for q in questions(sheets, [doc], scope_count=1, phase_count=0, schedule_count=1) if q.rule == "scanned"]


def test_a_specification_yields_division_26_sections():
    folder = corpus_path("Kittles Saxony/SPECS")
    if not os.path.isdir(folder):
        pytest.skip("corpus set not present: Kittles Saxony/SPECS")
    pdfs = [f for f in sorted(os.listdir(folder)) if f.lower().endswith(".pdf")]
    if not pdfs:
        pytest.skip("no spec PDF in Kittles Saxony/SPECS")
    found = []
    for f in pdfs:
        doc, _, _ = _read(f"Kittles Saxony/SPECS/{f}", "Specifications")
        found += spec_sections([doc])
    assert any(l.division == "26" for l in found), [l.text for l in found]
