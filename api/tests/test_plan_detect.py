"""The plan's derivation is pure: stored text in, typed lines out. No
database, no PDF. Every rule here is asserted on synthetic text; the
corpus assertions live in test_plan_corpus.py."""

from app.plan import copy
from app.plan.detect import DocIn, SheetIn, phases, questions, schedules, spec_sections


def doc(**o):
    d = dict(id="d1", filename="Spec.pdf", doc_type="Specifications", status="processed", context_text="", page_count=10)
    d.update(o)
    return DocIn(**d)


def sheet(**o):
    s = dict(id="s1", document_id="dd", number="E2.1", title="Power plan", kind="plan", page_index=3,
             scale='1/8" = 1\'-0"', scale_options=(), unreadable_reason="", schedule_text="")
    s.update(o)
    return SheetIn(**s)


DRAWINGS = doc(id="dd", filename="E-set.pdf", doc_type="Drawings")


# --- spec sections ---

def test_each_number_form_is_one_section():
    text = "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES\nblah\n260533 RACEWAYS AND BOXES\n27-15-00 Communications horizontal cabling\n28 31 00\nFIRE DETECTION AND ALARM\n"
    lines = spec_sections([doc(context_text=text)])
    assert [(l.division, l.text) for l in lines] == [
        ("26", "26 05 19 — LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"),
        ("26", "26 05 33 — RACEWAYS AND BOXES"),
        ("27", "27 15 00 — Communications horizontal cabling"),
        ("28", "28 31 00 — FIRE DETECTION AND ALARM"),
    ]
    assert lines[0].key == "spec:d1:260519"
    assert lines[0].place.quote == "SECTION 26 05 19 - LOW-VOLTAGE ELECTRICAL POWER CONDUCTORS AND CABLES"
    assert lines[0].place.page is None and lines[0].place.document_filename == "Spec.pdf"


def test_a_repeated_section_is_one_line_and_other_divisions_are_ignored():
    text = "26 05 19 CONDUCTORS\n23 05 00 HVAC\n26 05 19 CONDUCTORS (continued)\n"
    lines = spec_sections([doc(context_text=text)])
    assert [l.key for l in lines] == ["spec:d1:260519"]
    assert lines[0].place.quote == "26 05 19 CONDUCTORS"


def test_drawings_and_unprocessed_documents_contribute_no_sections():
    assert spec_sections([doc(doc_type="Drawings", context_text="26 05 19 X")]) == []
    assert spec_sections([doc(status="processing", context_text="26 05 19 X")]) == []


def test_a_bare_number_with_no_title_anywhere_is_dropped():
    assert spec_sections([doc(context_text="26 05 19\n\n")]) == []


# --- schedules ---

def test_schedule_and_legend_sheets_are_lines_and_plan_sheets_with_a_heading_are_too():
    rows = [
        sheet(id="a", number="E0.1", title="Luminaire schedule", kind="schedule", page_index=0),
        sheet(id="b", number="E0.2", title="Symbols legend", kind="legend", page_index=1),
        sheet(id="c", number="E4.1", title="Power plan", kind="plan", page_index=4,
              schedule_text="PANEL SCHEDULE LP-1\n... PANEL SCHEDULE LP-2"),
        sheet(id="d", number="E5.1", title="Lighting plan", kind="plan", page_index=5),
    ]
    lines = schedules(rows, [DRAWINGS])
    assert [(l.key, l.text, l.sheet_number, l.place.page) for l in lines] == [
        ("schedule:sheet:a", "Luminaire schedule", "E0.1", 1),
        ("schedule:sheet:b", "Symbols legend", "E0.2", 2),
        ("schedule:heading:c:PANEL SCHEDULE", "Panel schedule on E4.1", "E4.1", 5),
    ]
    assert lines[2].place.quote == "PANEL SCHEDULE LP-1"


def test_an_unreadable_sheet_is_never_a_schedule():
    rows = [sheet(id="a", kind="other", title="Scanned sheet", unreadable_reason="scan")]
    assert schedules(rows, [DRAWINGS]) == []


# --- phases ---

def test_phases_group_across_titles_notes_and_specs():
    rows = [
        sheet(id="a", number="D1", title="Phase 1 demolition plan", page_index=0),
        sheet(id="b", number="E2", title="PHASE 1 POWER PLAN", page_index=1),
        sheet(id="c", number="E3", title="Power plan", page_index=2, schedule_text="WORK IN PHASE II SHALL FOLLOW..."),
    ]
    spec = doc(context_text="Phase A work is limited to the north wing.\nThe next phase of the work...")
    lines = phases(rows, [DRAWINGS, spec])
    assert [(l.key, l.text) for l in lines] == [
        ("phase:PHASE 1", "Phase 1"), ("phase:PHASE II", "Phase II"), ("phase:PHASE A", "Phase A"),
    ]
    first = lines[0]
    assert first.place.quote == "Phase 1 demolition plan" and first.place.page == 1
    assert [p.page for p in first.places] == [1, 2]
    # "the next phase of" carries no number or letter, so it is not a phase.
    assert all("of" not in l.text for l in lines)


# --- questions ---

def q(rule, rows, docs, **counts):
    counts = {"scope_count": 0, "phase_count": 0, "schedule_count": 0, **counts}
    return [x for x in questions(rows, docs, **counts) if x.rule == rule]


def test_every_question_has_four_non_empty_fields():
    rows = [sheet(id="a", kind="other", title="Scanned sheet", unreadable_reason="scan"),
            sheet(id="b", number="E2.1", scale="", scale_options=())]
    for x in questions(rows, [DRAWINGS], scope_count=0, phase_count=0, schedule_count=0):
        assert x.title and x.found and x.why and x.fix and x.where


def test_scanned_counts_pages_per_document():
    rows = [sheet(id="a", document_id="dd", kind="other", unreadable_reason="scan", page_index=0),
            sheet(id="b", document_id="dd", kind="plan", page_index=1)]
    [x] = q("scanned", rows, [DRAWINGS])
    assert x.key == "question:scanned:dd" and x.document_id == "dd"
    assert x.found.startswith("1 of 2 pages in E-set.pdf")
    assert q("scanned", [sheet()], [DRAWINGS]) == []


def test_no_specs_no_scope_no_phasing_no_schedule_fire_on_the_project():
    rows = [sheet()]
    assert [x.key for x in q("no_specs", rows, [DRAWINGS])] == ["question:no_specs:project"]
    assert q("no_specs", rows, [DRAWINGS, doc()]) == []
    assert [x.key for x in q("no_scope", rows, [DRAWINGS])] == ["question:no_scope:project"]
    assert q("no_scope", rows, [DRAWINGS], scope_count=2) == []
    assert q("no_scope", rows, []) == []
    assert [x.key for x in q("no_phasing", rows, [DRAWINGS])] == ["question:no_phasing:project"]
    assert q("no_phasing", rows, [DRAWINGS], phase_count=1) == []
    assert [x.key for x in q("no_schedule", rows, [DRAWINGS])] == ["question:no_schedule:project"]
    assert q("no_schedule", rows, [DRAWINGS], schedule_count=1) == []
    # No readable plan sheet: neither phasing nor schedule is asked.
    scanned = [sheet(kind="other", unreadable_reason="scan")]
    assert q("no_phasing", scanned, [DRAWINGS]) == [] and q("no_schedule", scanned, [DRAWINGS]) == []


def test_no_scale_fires_per_readable_plan_sheet_without_a_scale():
    rows = [sheet(id="a", number="E2.1", scale="", scale_options=()),
            sheet(id="b", number="E2.2", scale="", scale_options=('1/8"',)),
            sheet(id="c", number="E0.1", kind="schedule", scale="")]
    [x] = q("no_scale", rows, [DRAWINGS])
    assert x.key == "question:no_scale:a" and "E2.1" in x.found and "E2.1" in x.where


def test_keys_are_stable_across_calls_and_quote_changes():
    a = spec_sections([doc(context_text="26 05 19 CONDUCTORS")])
    b = spec_sections([doc(context_text="SECTION 26 05 19 - CONDUCTORS AND CABLES")])
    assert a[0].key == b[0].key


def test_copy_never_names_internals():
    for words in (copy.scanned("x.pdf", 2, 2), copy.no_specs(), copy.no_scope(), copy.no_scale("E1", "Plan"),
                  copy.no_phasing(), copy.no_schedule()):
        joined = " ".join(words.values()).lower()
        assert not any(w in joined for w in ("model", "confidence", "llm", "ocr", "regex", "pattern"))
        assert "!" not in joined and "please" not in joined
