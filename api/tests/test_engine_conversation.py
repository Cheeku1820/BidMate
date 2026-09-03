"""Conversation agent: utterance + anchor -> typed proposal.

It routes and proposes. It never classifies, never writes, and never
approves (design spec 2.5). These tests are the boundary."""

import inspect

from app.engine import conversation
from app.engine.conversation import INTENTS, route


def test_exclusion_language_routes_to_exclude():
    p = route("ignore this wing, it's existing to remain", ["i1", "i2"])
    assert p.intent == "exclude"
    assert p.target_item_ids == ["i1", "i2"]


def test_reclassification_language_routes_to_reclassify():
    p = route("these six are all type F", ["a", "b", "c", "d", "e", "f"])
    assert p.intent == "reclassify"
    assert p.field == "name"


def test_context_language_routes_to_set_context():
    p = route("ceiling's 14 feet in here", ["x"])
    assert p.intent == "set_context"


def test_an_unrecognised_utterance_is_unknown_not_an_invented_action():
    p = route("what's the weather", ["x"])
    assert p.intent == "unknown"
    assert p.intent in INTENTS


def test_every_intent_is_in_the_closed_set():
    for message in ("ignore this area", "these are type F", "ceiling is 12 feet", "hello"):
        assert route(message, ["x"]).intent in INTENTS


def test_a_proposal_never_carries_a_classification_of_its_own():
    """It resolves WHICH items and WHICH field, then hands off. If it ever
    returns a catalog_id it has started classifying, and there are then two
    classifiers that will drift (spec 2.5 limit 1)."""
    p = route("these six are all type F", ["a"])
    assert not hasattr(p, "catalog_id")


def test_the_module_has_no_write_path():
    """Limit 2, enforced structurally rather than by convention: nothing in
    this module may touch a database session or a commit."""
    source = inspect.getsource(conversation)
    for forbidden in ("Session", "db.", "commit(", "sessionmaker"):
        assert forbidden not in source, f"conversation.py must not reference {forbidden}"


def test_no_anchor_yields_an_empty_target_list_not_a_guess():
    p = route("these are all type F", [])
    assert p.target_item_ids == []
