"""app/assistant/context.py -- what each screen puts in view. The
screen name is a closed set mirrored by src/components/conversation/
screenContext.jsx; a name outside it is a validation error, never a
guess."""
import uuid

import pytest
from pydantic import ValidationError

from app.assistant.context import ITEM_CAP, TEXT_CAP, build, clip_text
from app.assistant.schemas import SCREEN_NAMES, ScreenIn
from app.takeoff.models import Document, Item, Note, ReviewStatus, ScopeStatement, Sheet, Warning, WarningReason


def test_screen_names_are_the_closed_set():
    assert SCREEN_NAMES == (
        "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
        "notes", "labor", "pricing", "export", "settings",
    )


def test_screen_outside_the_set_is_refused():
    with pytest.raises(ValidationError):
        ScreenIn(name="dashboard")
    screen = ScreenIn(name="spreadsheet", sheet_id=uuid.uuid4(), view={"filter": "attention"})
    assert screen.view.filter == "attention"
    assert screen.item_id is None


def _screen(name, **kw):
    return ScreenIn(name=name, **kw)


def test_every_screen_gets_project_scope_and_notes(db, project, dana, sheet, item):
    db.add(Note(project_id=project.id, scope="project", title="LV excluded", body="Per scope letter.",
                category="exclusion", author_user_id=dana.id))
    db.flush()
    for name in SCREEN_NAMES:
        bundle = build(db, dana, project, _screen(name))
        assert bundle.project["name"] == "Meridian Distribution Center", name
        assert bundle.scope == [] and bundle.notes[0]["title"] == "LV excluded", name


def test_documents_screen_gets_documents_and_nothing_heavier(db, project, dana, sheet, item):
    db.add(Document(project_id=project.id, filename="E-set.pdf", doc_type="Drawings", content_type="application/pdf",
                    size_bytes=10, sha256="a" * 64, storage_key="k", status="processed", uploaded_by=dana.id,
                    page_count=4))
    db.flush()
    bundle = build(db, dana, project, _screen("documents"))
    assert [d["filename"] for d in bundle.documents] == ["E-set.pdf"]
    assert bundle.items is None and bundle.sheets is None and bundle.document_texts is None


def test_confirm_screen_gets_spec_text_but_not_drawing_text(db, project, dana):
    spec = Document(project_id=project.id, filename="spec-26.pdf", doc_type="Specifications",
                    content_type="application/pdf", size_bytes=10, sha256="b" * 64, storage_key="k2",
                    status="processed", uploaded_by=dana.id, context_text="Section 26 27 26: tamper-resistant.")
    drawings = Document(project_id=project.id, filename="E-set.pdf", doc_type="Drawings",
                        content_type="application/pdf", size_bytes=10, sha256="c" * 64, storage_key="k3",
                        status="processed", uploaded_by=dana.id, context_text="should not appear")
    db.add_all([spec, drawings])
    db.flush()
    bundle = build(db, dana, project, _screen("confirm"))
    assert [t["filename"] for t in bundle.document_texts] == ["spec-26.pdf"]
    assert bundle.document_texts[0]["text"] == "Section 26 27 26: tamper-resistant."
    assert bundle.document_texts[0]["omitted"] == 0


def test_takeoff_screen_narrows_items_to_the_sheet_and_summarizes_the_rest(db, project, dana, sheet, item):
    other = Sheet(project_id=project.id, number="E3.1", title="Lighting plan", discipline="Electrical",
                  revision="Rev 2", scale="1/8", scale_options=[], plan="warehouse", sort_order=2)
    db.add(other)
    db.flush()
    db.add(Item(project_id=project.id, sheet_id=other.id, symbol="fixture", name="Type F luminaire",
                system="Lighting", category="Fixtures", quantity=3, unit="EA", status=ReviewStatus.ATTENTION))
    db.flush()
    bundle = build(db, dana, project, _screen("takeoff", sheet_id=sheet.id))
    assert [i["name"] for i in bundle.items] == ["20A duplex receptacle"]
    assert bundle.other_sheets == [{"number": "E3.1", "counts": {"attention": 1}}]
    assert bundle.sheet_text["number"] == "E2.1"


def test_spreadsheet_is_project_wide_even_with_a_current_sheet(db, project, dana, sheet, item):
    """The spreadsheet lists every sheet's items; its sheet_id is only
    the row the estimator last came from. Narrowing there would answer
    "what's on the spreadsheet" with one sheet."""
    other = Sheet(project_id=project.id, number="E3.1", title="Lighting plan", discipline="Electrical",
                  revision="Rev 2", scale="1/8", scale_options=[], plan="warehouse", sort_order=2)
    db.add(other)
    db.flush()
    db.add(Item(project_id=project.id, sheet_id=other.id, symbol="fixture", name="Type F luminaire",
                system="Lighting", category="Fixtures", quantity=3, unit="EA", status=ReviewStatus.ATTENTION))
    db.flush()
    bundle = build(db, dana, project, _screen("spreadsheet", sheet_id=sheet.id))
    assert sorted(i["name"] for i in bundle.items) == ["20A duplex receptacle", "Type F luminaire"]
    assert bundle.other_sheets is None
    assert bundle.sheet_text["number"] == "E2.1"


def test_selected_item_comes_first(db, project, dana, sheet, item):
    first = Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name="Single-pole switch",
                 system="Lighting", category="Devices", quantity=2, unit="EA", status=ReviewStatus.READY)
    db.add(first)
    db.flush()
    bundle = build(db, dana, project, _screen("spreadsheet", item_id=item.id))
    assert bundle.items[0]["name"] == "20A duplex receptacle"
    assert bundle.items[0]["selected"] is True


def test_item_cap_collapses_overflow_to_counts(db, project, dana, sheet):
    for n in range(ITEM_CAP + 5):
        db.add(Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=f"Item {n}",
                    system="Power", category="Devices", quantity=1, unit="EA", status=ReviewStatus.READY))
    db.flush()
    bundle = build(db, dana, project, _screen("spreadsheet"))
    assert len(bundle.items) == ITEM_CAP
    assert bundle.item_overflow == {"omitted": 5, "per_sheet": {"E2.1": {"ready": 5}}}


def test_status_filter_is_counted_and_search_is_named(db, project, dana, sheet, item):
    db.add(Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name="Switch",
                system="Lighting", category="Devices", quantity=1, unit="EA", status=ReviewStatus.ATTENTION))
    db.flush()
    bundle = build(db, dana, project, _screen("spreadsheet", view={"filter": "attention", "search": "LP-2"}))
    assert bundle.view_note == (
        "The estimator has the spreadsheet filtered to Needs attention; 1 of 2 items match. "
        "The estimator has searched for 'LP-2'."
    )


def test_export_screen_lists_blocking_and_allowances(db, project, dana, sheet, item):
    item.status = ReviewStatus.MISSING
    db.add(Item(project_id=project.id, sheet_id=sheet.id, symbol="switch", name="Switch",
                system="Lighting", category="Devices", quantity=1, unit="EA", status=ReviewStatus.ATTENTION))
    db.flush()
    bundle = build(db, dana, project, _screen("export"))
    assert [i["name"] for i in bundle.blocking] == ["20A duplex receptacle"]
    assert [i["name"] for i in bundle.allowances] == ["Switch"]
    assert bundle.totals["counts"]["missing"] == 1


def test_warnings_ride_with_their_item(db, project, dana, sheet, item):
    # Warning has no project_id column, and its "where" field is the
    # attribute where_ (mapped to column "where"); WarningReason has no
    # CONFLICT member -- SCHEDULE_CONFLICT is the closest existing one.
    db.add(Warning(item_id=item.id, sheet_id=sheet.id, reason=WarningReason.SCHEDULE_CONFLICT,
                   title="Schedule conflict", found="Plan says 20A, schedule says 15A", why="Cost differs",
                   fix="Check the schedule", where_="E0.1 device schedule"))
    db.flush()
    bundle = build(db, dana, project, _screen("takeoff"))
    assert bundle.items[0]["warnings"][0]["title"] == "Schedule conflict"


def test_clip_text_cuts_at_a_paragraph_and_reports_the_rest():
    text = "para one\n\npara two\n\npara three"
    clipped, omitted = clip_text(text, cap=16)
    assert clipped == "para one"
    assert omitted == len(text) - len("para one")
    assert clip_text("short", cap=TEXT_CAP) == ("short", 0)
