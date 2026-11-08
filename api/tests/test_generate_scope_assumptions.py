"""Task 7 of docs/plans/rom-estimate.md -- the exclusions this estimate
applied because no document said either way.

The asymmetry here is deliberate and is the point of the whole section.
Boilerplate an electrical sub always excludes -- temporary power,
trenching, concrete pads -- names no counted work and removes no money,
so it is project-scoped and stated for the reader's benefit. An
exclusion that CAN remove counted work names the system it covers, so
the dollars it took out are traceable to the lines it took them from.
"""
from decimal import Decimal

import pytest

from app.estimate.basis import validate_assumption
from app.estimate.generate_scope import STANDARD_EXCLUSIONS, scope_assumptions
from app.takeoff.models import Document, ScopeStatement


@pytest.fixture
def document(db, project, dana):
    d = Document(project_id=project.id, filename="Scope letter.pdf", doc_type="scope",
                 content_type="application/pdf", size_bytes=1024, sha256="a" * 64,
                 storage_key="k/1", status="uploaded", uploaded_by=dana.id)
    db.add(d)
    db.flush()
    return d


def _statement(project, document, *, text, kind="excluded", status="found", quote=None):
    import uuid as _uuid

    return ScopeStatement(
        org_id=project.org_id, project_id=project.id, document_id=document.id,
        page_index=1, kind=kind, text=text, quote=quote if quote is not None else text,
        status=status, run_id=_uuid.uuid4(),
    )


def one(rows, *, title_contains):
    matches = [r for r in rows if title_contains.lower() in r["title"].lower()]
    assert len(matches) == 1, f"expected exactly one {title_contains!r}, got {[r['title'] for r in rows]}"
    return matches[0]


def test_silent_document_set_yields_standard_exclusions(db, project):
    a = one(scope_assumptions(db, project), title_contains="Temporary power")
    assert a["basis"] == "standard_exclusion"
    assert a["section"] == "scope"


def test_every_standard_exclusion_is_offered_when_nothing_is_said(db, project):
    """One row per SUBJECT, not one per boundary. Fire alarm emits a
    system row plus one per item-name keyword, because a counted
    fire-alarm device may be filed under "Life safety" alongside exit
    signs -- which are in scope, so the exclusion names the equipment
    rather than reaching for the whole system."""
    titles = {a["title"] for a in scope_assumptions(db, project)}
    assert titles == {e.title for e in STANDARD_EXCLUSIONS}


def test_an_included_statement_produces_no_exclusion_at_all(db, project, document):
    """The documents put the work IN the price, so nothing is assumed and
    nothing is removed. The bug this guards: keyword matching used to
    suppress the assumption regardless of direction, so a statement
    saying "included" read the same as one saying "by others"."""
    db.add(_statement(project, document,
                      text="Temporary power and lighting for construction is included.",
                      kind="included"))
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_a_stated_exclusion_still_removes_the_work(db, project, document):
    """The high-severity bug Codex found. A document saying "trenching by
    others" used to suppress the default assumption AND produce no
    exclusion record, so the work stayed in the price -- the exact
    inverse of "scope filters the number". It now emits an exclusion
    that quotes the document rather than claiming the estimate assumed
    it."""
    db.add(_statement(project, document, text="Trenching and backfill by others.",
                      kind="by_others"))
    db.flush()
    row = one(scope_assumptions(db, project), title_contains="Trenching")
    assert row["basis"] == "standard_exclusion"
    assert "The documents state it" in row["found"]
    assert "Trenching and backfill by others." in row["found"]
    assert row["where"] == "Scope, as read from the documents"


def test_an_alternate_is_read_as_out_of_this_number(db, project, document):
    """Priced separately is not priced here."""
    db.add(_statement(project, document, text="Trenching and backfill, alternate.",
                      kind="alternate"))
    db.flush()
    assert any("Trenching" in a["title"] for a in scope_assumptions(db, project))


def test_a_scope_letter_that_includes_everything_assumes_nothing(db, project, document):
    for exclusion in STANDARD_EXCLUSIONS:
        db.add(_statement(project, document, text=f"{exclusion.keywords[0]} is included.",
                          kind="included"))
    db.flush()
    assert scope_assumptions(db, project) == []


def test_a_scope_letter_that_excludes_everything_states_rather_than_assumes(db, project, document):
    """Every boundary addressed, so nothing is assumed -- but every one
    still has to remove its work, quoting the document that said so."""
    for exclusion in STANDARD_EXCLUSIONS:
        db.add(_statement(project, document, text=f"{exclusion.keywords[0]} is by others.",
                          kind="by_others"))
    db.flush()
    rows = scope_assumptions(db, project)
    assert rows
    assert all("The documents state it" in a["found"] for a in rows)


def test_a_dismissed_statement_does_not_address_the_topic(db, project, document):
    """A person dismissed it, so it is no longer what the documents say
    about this job -- the topic is open again and gets assumed."""
    db.add(_statement(project, document, text="Temporary power is included.",
                      status="dismissed"))
    db.flush()
    assert any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_a_confirmed_statement_addresses_the_topic(db, project, document):
    db.add(_statement(project, document, text="Temporary power is included.",
                      kind="included", status="confirmed"))
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_an_estimators_edit_is_read_as_the_statement(db, project, document):
    s = _statement(project, document, text="Something unrelated.", kind="by_others")
    s.edited_text = "Temporary power by the general contractor."
    db.add(s)
    db.flush()
    row = one(scope_assumptions(db, project), title_contains="Temporary power")
    # Quotes the estimator's correction, not the text it replaced.
    assert "Temporary power by the general contractor." in row["found"]


def test_matching_is_case_insensitive(db, project, document):
    db.add(_statement(project, document, text="TEMPORARY POWER BY OTHERS.", kind="by_others"))
    db.flush()
    row = one(scope_assumptions(db, project), title_contains="Temporary power")
    assert "The documents state it" in row["found"]


# --- what an exclusion is allowed to remove ----------------------------


def test_boilerplate_exclusions_are_project_scoped_and_remove_nothing(db, project):
    """No Division 26 takeoff counts trenching, so these must not reach
    for a system to delete."""
    rows = [a for a in scope_assumptions(db, project) if a["subject_kind"] == "project"]
    assert rows
    assert all(a.get("subject_ref") is None for a in rows)


def test_an_exclusion_that_can_remove_counted_work_names_its_subjects(db, project):
    rows = [a for a in scope_assumptions(db, project) if "Fire alarm" in a["title"]]
    assert {a["subject_kind"] for a in rows} == {"system", "name_like"}
    assert "Fire alarm" in {a["subject_ref"] for a in rows if a["subject_kind"] == "system"}


def test_the_fire_alarm_exclusion_does_not_reach_for_life_safety_wholesale(db, project):
    """Exit signs classify as "Life safety" and ARE Division 26 work
    this estimate includes. An exclusion naming that system to catch a
    fire-alarm device would silently remove them -- a smaller,
    internally consistent, confidently wrong number."""
    systems = {a["subject_ref"] for a in scope_assumptions(db, project)
               if a["subject_kind"] == "system"}
    assert "Life safety" not in systems


def test_fire_alarm_equipment_keywords_name_nothing_ambiguous(db, project):
    """Deliberately not "horn" or "bell", which appear in other
    contexts."""
    names = {a["subject_ref"] for a in scope_assumptions(db, project)
             if a["subject_kind"] == "name_like"}
    assert "horn" not in names
    assert "bell" not in names
    assert "fire alarm" in names


def test_every_name_scoped_exclusion_names_a_keyword(db, project):
    for a in scope_assumptions(db, project):
        if a["subject_kind"] == "name_like":
            assert a["subject_ref"]


def test_every_system_scoped_exclusion_names_a_system(db, project):
    """Without subject_ref a system exclusion covers nothing and
    silently removes no money, which reads as applied and is not --
    validate_assumption refuses it, and this is the generator-side
    guard so a bad entry fails here rather than at the write."""
    for a in scope_assumptions(db, project):
        if a["subject_kind"] == "system":
            assert a["subject_ref"]


# --- shape -------------------------------------------------------------


def test_every_generated_assumption_validates(db, project):
    rows = scope_assumptions(db, project)
    assert rows
    for a in rows:
        validate_assumption(a)


def test_every_assumed_exclusion_says_no_document_addressed_it(db, project):
    """The copy is re-pointed from the plan's "state it here as an
    answer" to "this estimate assumed it" -- a ROM has already made the
    call, and the reader needs to know which call was made."""
    for a in scope_assumptions(db, project):
        assert "not addressed" in a["found"].lower() or "no document" in a["found"].lower()


def test_no_generated_copy_names_a_model_or_a_confidence(db, project):
    rows = scope_assumptions(db, project)
    blob = " ".join(f"{a['title']} {a['found']} {a['why']} {a['where']}" for a in rows).lower()
    for forbidden in ("model", "confidence", "claude", "token", "prompt", "llm"):
        assert forbidden not in blob, forbidden


def test_standard_exclusions_have_unique_titles(db, project):
    titles = [e.title for e in STANDARD_EXCLUSIONS]
    assert len(titles) == len(set(titles))


def test_scope_assumptions_are_project_scoped(db, project, org, document):
    """Another project's scope letter must not silence this project's
    assumptions."""
    from app.takeoff.models import Project

    other = Project(org_id=org.id, name="Other job", revision_set_label="")
    db.add(other)
    db.flush()
    db.add(_statement(project, document, text="Temporary power is included."))
    db.flush()
    assert any("Temporary power" in a["title"] for a in scope_assumptions(db, other))


# --- the vocabulary gap (second Codex review, finding 2) ---------------


def test_an_equipment_name_the_documents_include_is_not_excluded(db, project, document):
    """The over-removal half. "Smoke detectors are included" matched none
    of the fire alarm KEYWORDS, so the boundary read as unaddressed, the
    default exclusion was assumed, and the smoke detector the documents
    had just put IN the price was removed from it.

    `StandardExclusion.vocabulary` now makes this structural rather than
    remembered: anything the exclusion can delete is also something a
    document can mention to take the decision away from it.
    """
    db.add(_statement(project, document, text="Smoke detectors are included.", kind="included"))
    db.flush()
    assert not any("Fire alarm" in a["title"] for a in scope_assumptions(db, project))


def test_every_removable_name_can_also_address_its_boundary(db, project):
    """The rule itself, over every exclusion rather than one example. A
    keyword list narrower than the delete list is a silent gap in
    whichever direction the document happens to word it."""
    for exclusion in STANDARD_EXCLUSIONS:
        for name in exclusion.item_names + exclusion.systems:
            assert name.lower() in exclusion.vocabulary, (exclusion.title, name)


def test_the_fire_alarm_exclusion_covers_the_equipment_a_real_set_carries(db, project):
    """The under-removal half. "Fire alarm by others" left `Heat
    detector` and `Horn strobe` in the price, because neither was on the
    name list -- an exclusion the document states and the number does
    not honour. Both punctuations of horn/strobe are covered, because a
    classifier writes whichever the legend used."""
    names = {a["subject_ref"] for a in scope_assumptions(db, project)
             if a["subject_kind"] == "name_like"}
    for equipment in ("heat detector", "horn/strobe", "horn strobe", "annunciator"):
        assert equipment in names, equipment


# --- origin (second Codex review, finding 13) --------------------------


def test_an_assumed_exclusion_is_assumed(db, project):
    rows = scope_assumptions(db, project)
    assert rows
    assert {a["origin"] for a in rows} == {"assumed"}


def test_a_stated_exclusion_is_counted_not_assumed(db, project, document):
    """The spec's own definition of counted includes "a scope statement
    extracted with a verbatim quote", and this row is one. Tagging it
    assumed told the reader the estimate had guessed at a boundary the
    scope letter spelled out, and it inflated the assumed tally by one
    row per subject the exclusion covers -- seven, for fire alarm."""
    db.add(_statement(project, document, text="Fire alarm by others.", kind="by_others"))
    db.flush()
    stated = [a for a in scope_assumptions(db, project) if "Fire alarm" in a["title"]]
    assert stated
    assert {a["origin"] for a in stated} == {"counted"}
    # Still an exclusion: it moved money, whatever it is tagged.
    assert {a["basis"] for a in stated} == {"standard_exclusion"}
