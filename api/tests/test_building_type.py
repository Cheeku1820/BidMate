"""Task 4 of docs/plans/estimate-without-asking.md -- what kind of job
this is, inferred from what the read job already stored.

Needed by exactly one completion case: a share of the electrical work
for a system absent from the whole job. A warehouse and a hospital carry
wildly different fire alarm scope, so that case cannot run without it --
and the spec's answer is to infer it, disclose it, ask about it, and
never block on it.

Deliberately not a language call. This product has one classifier
(CLAUDE.md: "two paths to a classification means two classifiers that
will drift"), and a deterministic guess that returns None under conflict
is more honest than a model's tiebreak would be.
"""
import uuid

import pytest

from app.estimate.building_type import TYPES, infer_building_type
from app.takeoff.models import Document, ScopeStatement, Sheet


@pytest.fixture
def scope_statement(db, project, dana):
    doc = Document(project_id=project.id, filename="scope-letter.pdf", doc_type="scope",
                   content_type="application/pdf", size_bytes=1, sha256="a" * 64,
                   storage_key="k", uploaded_by=dana.id)
    db.add(doc)
    db.flush()
    s = ScopeStatement(
        project_id=project.id, org_id=project.org_id, document_id=doc.id, page_index=0,
        kind="included", text="Nurse call and patient headwall rough-in by this contractor.",
        quote="Nurse call and patient headwall rough-in by this contractor.",
        run_id=uuid.uuid4(),
    )
    db.add(s)
    db.flush()
    return s


def _sheet(db, project, *, number, title="", schedule_text="", kind="plan"):
    s = Sheet(project_id=project.id, number=number, title=title, discipline="Electrical",
              revision="Rev 1", scale="", scale_options=[], plan="", kind=kind,
              schedule_text=schedule_text)
    db.add(s)
    db.flush()
    return s


def test_a_school_set_is_inferred_from_sheet_titles(db, project):
    _sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    assert infer_building_type(db, project)[0] == "school"


def test_a_healthcare_set_is_inferred_and_the_evidence_names_the_sheet(db, project):
    _sheet(db, project, number="E-1.0", title="Patient room power plan")
    kind, evidence = infer_building_type(db, project)
    assert kind == "healthcare"
    assert "E-1.0" in evidence


def test_an_estimators_own_choice_is_never_overwritten(db, project):
    """A person's judgment outranks an inference, always -- the same rule
    `merge.py` applies to an approved item and `write.py` to an
    overridden assumption."""
    _sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    project.building_type, project.building_type_source = "warehouse", "estimator"
    assert infer_building_type(db, project) is None


def test_a_previous_inference_is_reconsidered(db, project):
    """Only an estimator's choice is sacred. A re-read that now sees a
    classroom wing should be able to correct the engine's own last
    guess."""
    _sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    project.building_type, project.building_type_source = "warehouse", "inferred"
    assert infer_building_type(db, project)[0] == "school"


def test_nothing_to_go_on_returns_none(db, project):
    assert infer_building_type(db, project) is None


def test_a_sheet_with_no_signal_returns_none(db, project):
    _sheet(db, project, number="E-1.0", title="Power plan")
    assert infer_building_type(db, project) is None


def test_conflicting_signals_return_none_rather_than_the_loudest(db, project):
    """A tie is a real answer. Picking the first alphabetically, or the
    one with more keyword hits by a margin of one, would be a fabricated
    building type -- and a system allowance sized from a fabricated
    building is the number this product exists to prevent."""
    _sheet(db, project, number="E-1.0", title="Classroom wing")
    _sheet(db, project, number="E-2.0", title="Patient room")
    assert infer_building_type(db, project) is None


def test_a_schedule_is_read_as_well_as_a_title(db, project):
    _sheet(db, project, number="E-501", kind="schedule",
           schedule_text="Luminaire schedule — gymnasium high bay, classroom troffer")
    assert infer_building_type(db, project)[0] == "school"


def test_a_scope_statement_is_read_too(db, project, scope_statement):
    assert infer_building_type(db, project)[0] == "healthcare"


def test_every_inferred_type_is_in_the_closed_set(db, project):
    _sheet(db, project, number="E-1.0", title="Warehouse power plan")
    kind, _ = infer_building_type(db, project)
    assert kind in TYPES


def test_a_superseded_sheet_does_not_decide_the_building_type(db, project):
    """ROADMAP invariant 2 -- a superseded sheet contributes to nothing.
    An old revision naming a classroom wing that the current set no
    longer has must not size this job's fire alarm allowance."""
    from datetime import datetime, timezone

    old = _sheet(db, project, number="E-1.0", title="Classroom wing power plan")
    old.superseded_at = datetime.now(timezone.utc)
    db.flush()
    assert infer_building_type(db, project) is None
