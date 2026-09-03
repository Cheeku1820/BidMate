"""app/engine/estimate.py -- the path the API and the review workspace
actually run.

`pipeline.py` is the CLI's path and has its own end-to-end tests. This
module is the other one, and for a while the two priced different things:
`estimate.py` did its own catalog arithmetic and never called the Pricing
agent, so the product shipped every device bare -- no box, no plate, no
wire, no conduit -- while the CLI counted all of it. These tests pin the
two together.

Everything here except the last two cases runs without the real bid set,
so the guard holds in a container that has no drawings.
"""

import os

import pytest

from app.engine import estimate
from app.engine.catalog import CATALOG
from app.engine.contracts import ClassifiedItem, DetectedSheet, DeviceCluster, Placement
from tests.bid_set import BID

needs_bid_set = pytest.mark.skipif(not os.path.exists(BID), reason="real bid set not present")

SHEET = DetectedSheet(
    page_index=0, number="E2.1", title="Power plan", discipline="Electrical",
    scale='1/8" = 1\'-0"', width_pt=2448, height_pt=1584, region=(0, 0, 2448, 1584),
)


def _cluster(tag="R", n=10):
    return DeviceCluster(tag=tag, sheet_page_index=0, placements=[Placement(100, 100)] * n)


def _item(catalog_id="receptacle_20a", quantity=10):
    cat = CATALOG[catalog_id]
    return ClassifiedItem(
        catalog_id=catalog_id, name=cat.name, system=cat.system, category=cat.category,
        unit=cat.unit, symbol=cat.symbol, quantity=quantity, sheet_page_index=0,
        placements=[Placement(100, 100)] * quantity, status="ready", warning=None,
        source_tag="R",
    )


def test_the_deterministic_row_carries_its_assembly_material():
    """The regression this module exists for. A row priced at the bare
    catalog price is a receptacle with no box, no plate, and no branch
    wire behind it, and that is what the running product shipped."""
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    bare = CATALOG["receptacle_20a"].material_cost * 10
    assert row["material_cost"] > bare * 2, "assembly material is missing from the row"


def test_the_deterministic_row_carries_its_assembly_hours():
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    assert row["labor_hours"] > CATALOG["receptacle_20a"].labor_hours * 10


def test_material_factor_applies_to_the_assembly_too_and_only_once():
    """A box and a reel of #12 cost 45% more in Unalaska for the same
    reason the receptacle does. Applying the factor to the device half
    alone understates the job; applying it twice to that half overstates
    it. Both are caught by comparing against the unfactored row."""
    plain = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    local = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.45)
    assert local["material_cost"] == pytest.approx(plain["material_cost"] * 1.45, abs=0.02)


def test_a_location_does_not_change_how_long_an_install_takes():
    plain = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    local = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.45)
    assert local["labor_hours"] == plain["labor_hours"]


def test_labor_cost_uses_the_caller_rate_not_the_pricing_default():
    """`pricing.DEFAULT_LABOR_RATE` is a national placeholder. The app has
    already resolved the project's own rate by this point, and pricing a
    $98/hr job at $68 is a 30% error in the larger half of the total."""
    from app.engine.pricing import DEFAULT_LABOR_RATE

    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=98.0, material_factor=1.0)
    assert row["labor_cost"] == pytest.approx(row["labor_hours"] * 98.0, abs=0.02)
    assert row["labor_cost"] != pytest.approx(row["labor_hours"] * DEFAULT_LABOR_RATE, abs=0.02)


def test_an_unclassified_item_is_priced_at_zero_not_guessed():
    """Unchanged behaviour, pinned because it now runs through
    pricing.price_item: an item with no catalog entry contributes nothing
    rather than being invented a cost."""
    item = ClassifiedItem(
        catalog_id="unclassified", name="Unclassified symbol (VA)", system="Unknown",
        category="Unclassified", unit="ea", symbol="generic", quantity=12,
        sheet_page_index=0, placements=[Placement(1, 1)] * 12, status="attention",
        warning=None, source_tag="VA",
    )
    row = estimate._row_from_catalog(item, _cluster("VA", 12), [SHEET], labor_rate=98.0, material_factor=1.45)
    assert row["material_cost"] == 0
    assert row["labor_hours"] == 0
    assert row["total_cost"] == 0


def test_the_row_keys_are_unchanged():
    """ingest.py reads these by name. Adding to the row is safe; renaming
    or dropping one silently zeroes a column in the review workspace."""
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    required = {
        "name", "system", "category", "unit", "quantity", "status", "sheet", "page",
        "sheet_id", "tag", "x", "y", "placements", "material_cost", "labor_hours",
        "labor_cost", "total_cost", "symbol", "warning",
    }
    assert required <= set(row)


# --- the model-classified path: where the assembly key comes from -------


SPEC = {
    "tag": "R", "name": "20A duplex receptacle", "catalog_id": "receptacle_20a",
    "system": "Power", "category": "Devices", "unit": "ea",
    "material_cost": 12.0, "labor_hours": 0.5, "confidence": "high",
}


def test_the_classifier_is_asked_for_the_catalog_id_it_prices_against():
    """Assemblies are keyed by catalog id and this path produced none, so
    with an API key configured -- the normal case for a real project --
    every device was priced bare. The prompt now enumerates the closed
    list out of CATALOG itself, so a new catalog item is offered to the
    classifier without anyone remembering to edit a string."""
    from app.engine.llm import _prompt

    text = _prompt([{"tag": "R", "count": 5}], "", "Unalaska, AK")
    assert '"catalog_id"' in text
    for catalog_id in CATALOG:
        assert catalog_id in text, f"{catalog_id} is not offered to the classifier"


def test_a_catalog_id_resolves_its_assembly():
    assert estimate.resolve_assembly_parent(SPEC) == "receptacle_20a"


def test_an_exact_catalog_name_resolves_when_the_id_is_absent():
    spec = {**SPEC}
    del spec["catalog_id"]
    assert estimate.resolve_assembly_parent(spec) == "receptacle_20a"


def test_an_unrecognised_catalog_id_resolves_to_nothing_not_to_a_guess():
    """Model output is data. An id that is not in CATALOG -- invented,
    misspelled, or the literal "none" the prompt offers -- must resolve to
    no assembly, so the item is priced bare rather than roughed in as
    something it may not be."""
    for value in ("none", "", "receptacle", "recept_20a", None, 7):
        assert estimate.resolve_assembly_parent({**SPEC, "catalog_id": value, "name": "Wall pack"}) is None


def test_the_symbol_field_is_not_used_as_the_assembly_key():
    """The rejected candidate, pinned so it is not reintroduced. `symbol`
    does not separate the panelboard from the disconnect -- both carry
    symbol "panel" -- and their assemblies differ by about seven times in
    material, so a symbol map is wrong on the most expensive cell in the
    catalog. It is also never returned: the classifier is not asked for
    one."""
    from app.engine.assemblies import expand

    assert CATALOG["panel"].symbol == CATALOG["disconnect"].symbol
    assert expand("panel", 1).material_cost > expand("disconnect", 1).material_cost * 5
    assert estimate.resolve_assembly_parent(
        {"symbol": "receptacle", "name": "Something else", "category": "Devices",
         "material_cost": 40.0, "labor_hours": 0.9}
    ) is None


def test_a_model_classified_row_carries_its_assembly():
    row = estimate._row_from_spec(SPEC, _cluster(), [SHEET], 68.0, 1.0, "receptacle_20a")
    bare = estimate._row_from_spec(SPEC, _cluster(), [SHEET], 68.0, 1.0, None)
    assert row["material_cost"] > bare["material_cost"] * 2
    assert row["labor_hours"] > bare["labor_hours"]


def test_material_factor_applies_once_to_the_whole_model_classified_row():
    plain = estimate._row_from_spec(SPEC, _cluster(), [SHEET], 68.0, 1.0, "receptacle_20a")
    local = estimate._row_from_spec(SPEC, _cluster(), [SHEET], 68.0, 1.45, "receptacle_20a")
    assert local["material_cost"] == pytest.approx(plain["material_cost"] * 1.45, abs=0.02)


def test_an_unresolved_row_is_priced_bare_not_roughed_in_as_a_guess():
    row = estimate._row_from_spec(SPEC, _cluster(), [SHEET], 68.0, 1.0, None)
    assert row["material_cost"] == pytest.approx(12.0 * 10, abs=0.01)
    assert row["labor_hours"] == pytest.approx(0.5 * 10, abs=0.01)


# --- the feet-per-device disclosure -------------------------------------


def test_the_wiring_assumption_is_disclosed_on_the_project():
    """FEET_PER_DEVICE is a rule of thumb, not a measurement -- the drawing
    carries a homerun arrow, not a route. Producing wire and conduit
    quantities from it without saying so is the silent guess ROADMAP 2.1
    names as the thing this product exists to prevent."""
    from app.engine.assemblies import FEET_PER_DEVICE

    note = estimate._wiring_note(assembly_applied=True, bare_names=set())
    assert f"{FEET_PER_DEVICE:g} feet per device" in note
    assert "conduit" in note.lower() and "wire" in note.lower()


def test_the_wiring_note_names_nothing_the_estimator_cannot_act_on():
    """Product language: sentence case, plain construction terms, no model
    name, no percentage, no processing internal. Also no invented control
    -- there is no company-settings field for feet per device, so the note
    must not send an estimator looking for one."""
    from app.takeoff.ingest import BANNED_PHRASES

    note = estimate._wiring_note(assembly_applied=True, bare_names={"Wall pack"})
    # The same patterns the API boundary already enforces on every
    # warning, applied to the note that sits beside them. Matched on word
    # boundaries there, which is why "against" does not read as "AI".
    for pattern in BANNED_PHRASES:
        assert not pattern.search(note), f"{pattern.pattern!r} does not belong in estimator copy"
    # No invented control, and no engine-internal identifier.
    for phrase in ("company settings", "catalog_id", "assembly key", "pipeline"):
        assert phrase not in note.lower()
    assert note == note[0].upper() + note[1:]


def test_items_priced_without_a_rough_in_are_counted_in_the_note():
    note = estimate._wiring_note(assembly_applied=True, bare_names={"Wall pack", "Nurse call station"})
    assert "2 item types" in note
    one = estimate._wiring_note(assembly_applied=True, bare_names={"Wall pack"})
    assert "1 item type" in one and "was priced" in one


def test_no_note_when_nothing_was_assumed():
    assert estimate._wiring_note(assembly_applied=False, bare_names=set()) == ""


def test_the_disclosure_is_not_a_per_item_warning():
    """A warning is tied to non-`ready` status, so warning every item that
    carries wire would move essentially the whole takeoff to Needs
    attention and leave the review queue meaning nothing. The assumption
    is stated once, on the project."""
    row = estimate._row_from_catalog(_item(), _cluster(), [SHEET], labor_rate=68.0, material_factor=1.0)
    assert row["status"] == "ready"
    assert row["warning"] is None


# --- the model-classified branch of _compute, end to end ----------------
#
# The two cases above exercise the row builder and the resolver directly.
# These run the branch itself against the real set, with the model call
# stubbed, because the wiring between them -- which spec reaches which
# cluster, what gets counted as unresolved -- is where this path was
# broken and is not covered by testing either half alone.

def _stub_llm(monkeypatch, item_for):
    from app.engine import llm

    def fake_estimate(tags, schedule_text, location):
        return {
            "location_labor_rate": 98.0,
            "material_factor": 1.35,
            "location_note": "Rate based on Unalaska, AK area cost data.",
            "items": [item_for(t["tag"]) for t in tags],
        }

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "estimate", fake_estimate)


@needs_bid_set
def test_the_model_path_prices_rough_in_when_the_catalog_id_resolves(monkeypatch):
    _stub_llm(monkeypatch, lambda tag: {
        "tag": tag, "name": "20A duplex receptacle", "catalog_id": "receptacle_20a",
        "system": "Power", "category": "Devices", "unit": "ea",
        "material_cost": 12.0, "labor_hours": 0.5, "confidence": "high",
    })
    rows, _sheets, meta = estimate._compute(BID, "Unalaska, AK")

    assert meta["source"] == "llm"
    assert rows, "the model path produced no rows"
    for row in rows:
        assert row["material_cost"] > 12.0 * row["quantity"] * meta["material_factor"], \
            "a resolved row is still priced as a bare device"
    assert "30 feet per device" in meta["wiring_note"]
    assert "could not be matched" not in meta["wiring_note"]


@needs_bid_set
def test_the_model_path_discloses_what_it_could_not_rough_in(monkeypatch):
    """An unresolved item is priced bare, which understates it. The
    understatement is stated on the project rather than left to be
    noticed as a low number."""
    _stub_llm(monkeypatch, lambda tag: {
        "tag": tag, "name": "Nurse call station", "catalog_id": "none",
        "system": "Low voltage", "category": "Devices", "unit": "ea",
        "material_cost": 40.0, "labor_hours": 0.9, "confidence": "high",
    })
    rows, _sheets, meta = estimate._compute(BID, "Unalaska, AK")

    assert rows
    for row in rows:
        assert row["material_cost"] == pytest.approx(
            40.0 * row["quantity"] * meta["material_factor"], abs=0.02)
    assert "1 item type (Nurse call station) could not be matched" in meta["wiring_note"]
    assert "30 feet per device" not in meta["wiring_note"], \
        "nothing carried an assembly, so nothing assumed a wiring length"


# --- an item the classifier declined to price gets no assembly ----------


UNCLASSIFIED_SPEC = {
    "tag": "VA", "name": "20A duplex receptacle", "catalog_id": "receptacle_20a",
    "system": "Unknown", "category": "Unclassified", "unit": "ea",
    "material_cost": 0, "labor_hours": 0, "confidence": "low",
}


def test_an_item_the_model_reported_unclassified_gets_no_assembly():
    """The prompt tells the model two things about a non-device tag: report
    it Unclassified with no cost, and pick catalog_id "none". Obeying the
    first and not the second turned a $0 row into a full receptacle
    rough-in -- $2,773.64 on a 12-count VA tag at the Unalaska index.

    18 of the 45 clusters on the real set are exactly these tags, so this
    is the common case rather than an edge one, and it runs opposite to
    every other refusal in the engine: pricing.py declines to guess a
    price for an unclassified item, and this fabricated one."""
    assert estimate.resolve_assembly_parent(UNCLASSIFIED_SPEC) is None

    row = estimate._row_from_spec(
        UNCLASSIFIED_SPEC, _cluster("VA", 12), [SHEET], 110.0, 1.45,
        estimate.resolve_assembly_parent(UNCLASSIFIED_SPEC),
    )
    assert row["material_cost"] == 0
    assert row["labor_hours"] == 0
    assert row["total_cost"] == 0


def test_an_item_priced_at_zero_gets_no_assembly_whatever_its_category():
    """The category is one signal and the cost is the other. A model that
    labels a junk tag "Devices" but prices it at nothing has still
    declined to treat it as a device."""
    spec = {**UNCLASSIFIED_SPEC, "system": "Power", "category": "Devices"}
    assert estimate.resolve_assembly_parent(spec) is None


def test_a_real_device_is_unaffected_by_the_guard():
    """The guard must refuse only what the classifier refused."""
    assert estimate.resolve_assembly_parent(SPEC) == "receptacle_20a"


def test_an_explicit_none_is_not_overturned_by_the_item_name():
    """"none" is an answer, not a gap. The name resolver exists for a
    response that omitted the id, not to reverse one that declined it."""
    spec = {**SPEC, "catalog_id": "none"}
    assert estimate.resolve_assembly_parent(spec) is None


def test_a_catalog_id_resolves_whatever_its_case():
    assert estimate.resolve_assembly_parent({**SPEC, "catalog_id": "PANEL"}) == "panel"
    assert estimate.resolve_assembly_parent({**SPEC, "catalog_id": " Receptacle_20A "}) == "receptacle_20a"


def test_a_nonsense_cost_reads_as_unpriced_rather_than_raising():
    """Model output is data. A string where a number belongs must not
    raise out of the middle of a takeoff, and reading it as zero fails
    toward unpriced -- the direction the engine already refuses in."""
    assert estimate.resolve_assembly_parent({**SPEC, "material_cost": "n/a", "labor_hours": None}) is None


def test_the_note_names_the_items_it_could_not_match():
    """A count tells an estimator a correction is needed; a name tells
    them where. Capped so a bad set cannot turn the basis note into a
    list."""
    one = estimate._wiring_note(True, {"Wall pack"})
    assert "(Wall pack)" in one

    many = estimate._wiring_note(True, {"Wall pack", "Nurse call station", "Isolated power panel", "Patient headwall"})
    assert "and 1 others" in many or "and 1 other" in many
    assert "Isolated power panel" in many
