"""Task 1 of docs/plans/rom-estimate.md -- the basis vocabulary is closed
and carries the spreads the spec's table names, and an assumption missing
its basis or its evidence pointer is refused at the boundary the way
`ingest.validate_warning` refuses a warning missing one of its five
fields.
"""
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.estimate.basis import BASIS, SECTIONS, validate_assumption


def test_basis_set_is_closed_and_carries_spreads():
    assert set(BASIS) == {
        "supplier_quote", "firm_default", "market_estimate", "class_average",
        "inferred", "rule_of_thumb", "scaled", "standard_exclusion", "estimator_entered",
    }
    assert BASIS["supplier_quote"].spread == Decimal("0")
    assert BASIS["standard_exclusion"].spread == Decimal("0")
    assert BASIS["firm_default"].spread == Decimal("0.10")
    assert BASIS["market_estimate"].spread == Decimal("0.15")
    assert BASIS["class_average"].spread == Decimal("0.20")
    assert BASIS["scaled"].spread == Decimal("0.20")
    assert BASIS["inferred"].spread == Decimal("0.25")
    assert BASIS["rule_of_thumb"].spread == Decimal("0.25")
    # A number a person entered is not an estimate, the same reading a
    # supplier's quote gets.
    assert BASIS["estimator_entered"].spread == Decimal("0")


def test_every_basis_carries_estimator_facing_label():
    for key, spec in BASIS.items():
        assert spec.label.strip(), key
        # No model names, no processing internals, no confidence framing.
        lowered = spec.label.lower()
        assert "model" not in lowered
        assert "confidence" not in lowered


def test_sections_are_the_four_the_spec_names():
    assert SECTIONS == ("scope", "takeoff", "labor", "material")


def test_validate_assumption_refuses_missing_basis():
    with pytest.raises(DomainError) as e:
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "where": "EL101"})
    assert e.value.code == "invalid_assumption"


def test_validate_assumption_refuses_missing_where():
    with pytest.raises(DomainError) as e:
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "rule_of_thumb"})
    assert e.value.code == "invalid_assumption"


def test_validate_assumption_refuses_unknown_basis():
    with pytest.raises(DomainError):
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "vibes", "where": "EL101"})


def test_validate_assumption_refuses_unknown_section():
    with pytest.raises(DomainError):
        validate_assumption({"section": "vibes", "title": "t", "found": "f",
                             "why": "w", "basis": "scaled", "where": "EL101"})


def test_validate_assumption_refuses_a_non_dict():
    with pytest.raises(DomainError):
        validate_assumption("temporary power excluded")


def test_validate_assumption_refuses_whitespace_only_field():
    with pytest.raises(DomainError):
        validate_assumption({"section": "takeoff", "title": "   ", "found": "f",
                             "why": "w", "basis": "scaled", "where": "EL101"})


def test_validate_assumption_returns_a_normalized_record():
    out = validate_assumption({
        "section": " takeoff ", "title": " Showroom ceiling height ",
        "found": " No reflected ceiling plan in the set ",
        "why": " Fixture drop lengths depend on it ",
        "basis": " inferred ", "where": " EL101 ",
        "value": " 14 ", "unit": " ft ",
    })
    assert out["section"] == "takeoff"
    assert out["title"] == "Showroom ceiling height"
    assert out["basis"] == "inferred"
    assert out["where"] == "EL101"
    assert out["value"] == "14"
    assert out["unit"] == "ft"
    # Defaults the generators rely on rather than each setting by hand.
    assert out["subject_kind"] == "project"
    assert out["subject_id"] is None
    assert out["source"] == "engine"


def test_validate_assumption_refuses_unknown_subject_kind():
    with pytest.raises(DomainError):
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "scaled", "where": "E",
                             "subject_kind": "wing"})


def test_validate_assumption_refuses_unknown_source():
    with pytest.raises(DomainError):
        validate_assumption({"section": "takeoff", "title": "t", "found": "f",
                             "why": "w", "basis": "scaled", "where": "E",
                             "source": "the_engine_probably"})


def test_assumption_row_round_trips(db, project):
    """The ORM model exists and the four-field shape survives a flush."""
    from app.takeoff.models import Assumption

    row = Assumption(
        project_id=project.id, section="takeoff", subject_kind="project",
        title="Showroom ceiling height", found="No reflected ceiling plan in the set",
        why="Fixture drop lengths depend on it", where="EL101",
        basis="inferred", value="14", unit="ft", source="engine",
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    assert row.id is not None
    assert row.created_at is not None
    assert row.excluded_value is None
