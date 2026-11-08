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
    rows = scope_assumptions(db, project)
    assert len(rows) == len(STANDARD_EXCLUSIONS)


def test_an_addressed_exclusion_is_not_assumed(db, project, document):
    db.add(_statement(project, document,
                      text="Temporary power and lighting for construction is included.",
                      kind="included"))
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_an_exclusion_the_documents_already_state_is_not_assumed(db, project, document):
    """The document saying "trenching by others" is a counted scope
    statement. Repeating it as an assumption would disclose a fact the
    documents carry, which overstates what had to be assumed."""
    db.add(_statement(project, document, text="Trenching and backfill by others.",
                      kind="by_others"))
    db.flush()
    assert not any("Trenching" in a["title"] for a in scope_assumptions(db, project))


def test_extracted_scope_statements_are_not_assumptions(db, project, document):
    """A scope letter that addresses everything leaves nothing to
    assume."""
    for exclusion in STANDARD_EXCLUSIONS:
        db.add(_statement(project, document, text=f"{exclusion.keywords[0]} is by others."))
    db.flush()
    assert scope_assumptions(db, project) == []


def test_a_dismissed_statement_does_not_address_the_topic(db, project, document):
    """A person dismissed it, so it is no longer what the documents say
    about this job -- the topic is open again and gets assumed."""
    db.add(_statement(project, document, text="Temporary power is included.",
                      status="dismissed"))
    db.flush()
    assert any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_a_confirmed_statement_addresses_the_topic(db, project, document):
    db.add(_statement(project, document, text="Temporary power is included.",
                      status="confirmed"))
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_an_estimators_edit_is_read_as_the_statement(db, project, document):
    s = _statement(project, document, text="Something unrelated.")
    s.edited_text = "Temporary power by the general contractor."
    db.add(s)
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


def test_matching_is_case_insensitive(db, project, document):
    db.add(_statement(project, document, text="TEMPORARY POWER BY OTHERS."))
    db.flush()
    assert not any("Temporary power" in a["title"] for a in scope_assumptions(db, project))


# --- what an exclusion is allowed to remove ----------------------------


def test_boilerplate_exclusions_are_project_scoped_and_remove_nothing(db, project):
    """No Division 26 takeoff counts trenching, so these must not reach
    for a system to delete."""
    rows = [a for a in scope_assumptions(db, project) if a["subject_kind"] == "project"]
    assert rows
    assert all(a.get("subject_ref") is None for a in rows)


def test_an_exclusion_that_can_remove_counted_work_names_its_system(db, project):
    a = one(scope_assumptions(db, project), title_contains="Fire alarm")
    assert a["subject_kind"] == "system"
    assert a["subject_ref"] == "Fire alarm"


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


def test_every_exclusion_says_it_was_assumed_and_can_be_changed(db, project):
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
