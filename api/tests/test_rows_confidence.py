"""Task 3 of docs/plans/estimate-without-asking.md -- every counted line
carries a confidence and the reasons that produced it.

Before this, `rows.py` consumed the classifier's own confidence to pick
a status and then threw it away, so the spreadsheet had no way to rank a
400-item sheet by what is worth checking. The status channel is
deliberately left exactly as it was: this task adds a channel, it does
not change routing.

Imports the engine, which the API process may not
(`test_api_import_boundary.py`) -- a test is not the API process, the
same licence `test_the_feet_per_device_rule_mirrors_the_engine` takes.
"""
from types import SimpleNamespace

from app.engine.contracts import DeviceCluster, Placement
from app.engine.rows import _row_from_catalog, _row_from_spec

SHEETS = [SimpleNamespace(number="E2.1", page_index=0)]


def _cluster(tag="R", count=14):
    return DeviceCluster(
        tag=tag, sheet_page_index=0,
        placements=[Placement(x=100 + i, y=200) for i in range(count)],
    )


def _spec(confidence="high", basis=None, **kw):
    spec = {
        "name": "20A duplex receptacle", "system": "Power", "category": "Devices",
        "unit": "ea", "confidence": confidence, "material_cost": 12.0, "labor_hours": 0.5,
        "classification_basis": basis,
    }
    spec.update(kw)
    return spec


def _row(confidence="high", basis=None, **kw):
    return _row_from_spec(_spec(confidence, basis, **kw), _cluster(), SHEETS, 78.0, 1.0)


def test_a_legend_matched_row_scores_nine():
    assert _row(confidence="high", basis=None)["confidence"] == 9


def test_a_row_named_from_context_scores_lower_than_a_matched_one():
    """`classification_basis == "inferred"` is the engine's own record
    that no legend on the set defines this tag."""
    assert _row(confidence="high", basis="inferred")["confidence"] < 9


def test_a_row_not_in_the_legend_says_so_among_its_reasons():
    reasons = " ".join(_row(confidence="high", basis="inferred")["confidence_reasons"])
    assert "legend" in reasons.lower()


def test_a_low_confidence_row_keeps_attention_and_scores_six():
    row = _row(confidence="low")
    assert row["status"] == "attention"
    assert row["confidence"] == 6


def test_confidence_does_not_change_the_status_channel():
    """Three independent channels (CLAUDE.md): glyph, ring colour, badge
    -- and now a fourth number that must not collapse into any of them.
    A high-confidence row is `ready` and a low one is `attention`,
    exactly as before this column existed."""
    assert _row(confidence="high")["status"] == "ready"
    assert _row(confidence="medium")["status"] == "attention"


def test_every_scored_row_can_say_why():
    row = _row(confidence="medium")
    assert row["confidence_reasons"]
    assert all(isinstance(r, str) and r for r in row["confidence_reasons"])


def test_the_deterministic_path_matched_the_legend_by_construction():
    """`_row_from_catalog` resolves against the legend to exist at all,
    so its quantity is as well evidenced as a counted line gets."""
    item = SimpleNamespace(
        name="20A duplex receptacle", system="Power", category="Devices", unit="ea",
        quantity=14, status="ready", symbol="receptacle", source_tag="R", warning=None,
        catalog_id="receptacle_duplex_20a",
    )
    row = _row_from_catalog(item, _cluster(), SHEETS, 78.0, 1.0)
    assert row["confidence"] == 9
    assert row["confidence_reasons"]


def test_no_reason_is_a_percentage_or_a_model_name():
    """CLAUDE.md: never surface model names or processing internals. The
    score is admissible only because every reason is a plain sentence
    about which method produced the number."""
    for confidence in ("high", "medium", "low"):
        for basis in (None, "inferred"):
            for reason in _row(confidence, basis)["confidence_reasons"]:
                low = reason.lower()
                assert "%" not in reason
                assert not any(w in low for w in ("model", "prompt", "token", "claude", "confidence score"))
