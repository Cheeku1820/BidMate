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


# --- a key is a token, never a substring ---------------------------------
#
# The second bug in this module, and the more dangerous one. Longest-match
# fixed which of two *real* matches wins; it could not help when the match
# itself was spurious, because "NC" inside CONCORD and "NH" are both two
# characters long.


def test_a_state_code_inside_a_city_name_is_not_a_match():
    """The failure this class produces is the one the product exists to
    prevent: NH is not in the table, so "Concord, NH" should fall to the
    national default and visibly carry the national note. Instead "NC"
    matched inside CONCORD and a New Hampshire job was priced against
    North Carolina -- roughly 15% low, with nothing on screen saying a
    fallback had happened at all."""
    rate, factor, note = lookup("Concord, NH")
    assert (rate, factor) == NATIONAL
    assert "National average" in note
    assert (rate, factor) != _TABLE["NC"]


def test_a_real_trailing_state_code_still_resolves():
    """The fix must not cost the state rows their job."""
    assert lookup("Charlotte, NC")[:2] == _TABLE["NC"]
    assert lookup("Fairbanks, AK")[:2] == _TABLE["AK"]
    assert lookup("AK")[:2] == _TABLE["AK"], "a bare state code with no city still resolves"


def test_the_near_misses_now_resolve_by_rule_rather_than_by_luck():
    """Both of these contain "CO" and both returned the right row before
    the fix -- but only because OH and FL happen to precede CO in the
    table and `max` keeps the first of equal-length matches. Insertion
    order is not a rule. Under token matching, CO is not a candidate at
    all for either."""
    assert lookup("Columbus, OH")[:2] == _TABLE["OH"]
    assert lookup("Cocoa, FL")[:2] == _TABLE["FL"]


def test_a_name_inside_a_longer_word_is_not_a_match():
    """The same rule for the non-code keys: ALASKA must not match inside
    UNALASKA, which is what makes UNALASKA's own row meaningful."""
    assert lookup("Unalaska, AK")[:2] == _TABLE["UNALASKA"]
    assert lookup("Unalaska, AK")[:2] != _TABLE["ALASKA"]


def test_longest_match_still_wins_among_names():
    """A location naming both the city and the state resolves to the city."""
    assert lookup("Unalaska Alaska")[:2] == _TABLE["UNALASKA"]
    assert lookup("Alaska")[:2] == _TABLE["ALASKA"]


def test_no_key_can_be_matched_from_inside_another_word():
    """The structural guard, and the one that would have caught this class
    rather than these three instances.

    For every key in the table, a fabricated location that contains it as
    a *substring* of a longer word -- but does not name it as a token --
    must not resolve to that key. Carrying a trailing state that is in the
    table checks the same thing from the other side: the real trailing
    token must win, not the buried substring.

    Written over `_TABLE` rather than as a case list so a key added later
    is covered the day it is added.
    """
    leaks = []
    for key in _TABLE:
        buried = f"X{key}X"
        if lookup(f"{buried}, ZZ")[:2] != NATIONAL:
            leaks.append((key, "matched from inside a word"))
        other = "TX" if key != "TX" else "CA"
        if lookup(f"{buried}, {other}")[:2] != _TABLE[other]:
            leaks.append((key, f"beat the real trailing {other}"))
    assert leaks == [], f"keys matchable as substrings: {leaks}"


def test_a_trailing_zip_code_does_not_hide_the_state():
    """The trailing token is the last run of letters, not the last
    whitespace-delimited chunk, so a posted address still resolves."""
    assert lookup("Unalaska, AK 99685")[:2] == _TABLE["UNALASKA"]
    assert lookup("Fairbanks, AK 99701")[:2] == _TABLE["AK"]
