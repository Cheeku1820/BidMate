"""app/engine/regions.py -- the deterministic location price index.

The table holds two kinds of key: two-letter state codes, and city or
metro names under them. A state code is a substring of every "City, ST"
string that names a city in that state, so the two kinds compete on
every realistic input and which one wins is the whole behaviour of this
module.
"""

from app.engine.regions import NATIONAL, _TABLE, lookup


def test_a_city_row_is_reachable_when_its_state_code_is_also_in_the_table():
    """The regression, and it was not one row: `_TABLE` was scanned in
    insertion order and "AK" is listed before "UNALASKA", so "AK" matched
    inside "UNALASKA, AK" first and returned. Every city and metro row in
    the table was unreachable the same way -- the specific half of the
    table was dead, and the real bid set was priced against the state row
    at $98/1.35 rather than the $110/1.45 the table holds for it."""
    assert lookup("Unalaska, AK")[:2] == _TABLE["UNALASKA"]
    assert lookup("Anchorage, AK")[:2] == _TABLE["ANCHORAGE"]
    assert _TABLE["UNALASKA"] != _TABLE["AK"], "this test proves nothing if the two rows agree"


def test_every_city_row_in_the_table_is_reachable():
    """Written as a sweep rather than a case per city, because the failure
    was structural: nothing about Unalaska caused it, and adding a city to
    the table must not quietly add another unreachable row."""
    cities = {
        "UNALASKA": "AK", "ANCHORAGE": "AK", "HONOLULU": "HI", "NEW YORK": "NY",
        "MANHATTAN": "NY", "SAN FRANCISCO": "CA", "LOS ANGELES": "CA",
        "SEATTLE": "WA", "CHICAGO": "IL", "BOSTON": "MA", "HOUSTON": "TX",
        "DALLAS": "TX",
    }
    unreachable = [
        city for city, state in cities.items()
        if lookup(f"{city.title()}, {state}")[:2] != _TABLE[city]
    ]
    assert unreachable == [], f"city rows shadowed by their state code: {unreachable}"


def test_a_city_with_no_row_of_its_own_still_falls_back_to_its_state():
    """The state rows are the fallback, not collateral damage. A city the
    table does not name must still be priced against its state."""
    assert lookup("Fairbanks, AK")[:2] == _TABLE["AK"]
    assert lookup("Spokane, WA")[:2] == _TABLE["WA"]


def test_a_location_matching_nothing_returns_the_national_default():
    for location in ("Nowhere, ZZ", "", None):
        rate, factor, note = lookup(location)
        assert (rate, factor) == NATIONAL
        assert "National average" in note


def test_the_note_names_the_location_the_estimator_typed():
    note = lookup("Unalaska, AK")[2]
    assert note == "Rate based on Unalaska, AK area cost data."
