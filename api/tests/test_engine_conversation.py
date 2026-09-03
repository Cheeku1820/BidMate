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
    returned a catalog label there would be two classifiers, and when they
    drift every per-agent accuracy number stops meaning anything (spec 2.5
    limit 1). The dataclass shape guarantees no catalog_id field; this also
    pins the behaviour, since a reclassify proposal that filled `value`
    with a guessed item name would satisfy the shape and still break the
    limit."""
    p = route("these six are all type F", ["a"])
    assert not hasattr(p, "catalog_id")
    assert p.intent == "reclassify"
    assert p.field == "name"
    assert p.value == "", "Conversation must not supply the label -- Classification does"


def test_the_module_has_no_write_path():
    """Tripwire, not a guarantee: a plain substring scan for the obvious
    spellings of a write path. It catches an accidental `db.session.commit()`
    dropped in during later edits, but it is trivially defeated by anything
    that doesn't spell the forbidden words literally -- e.g.
    `getattr(x, "comm" + "it")` matches none of these substrings and would
    still perform a write. The structural check that actually backs limit 2
    is test_the_module_imports_nothing_that_could_write below, which looks
    at what the module can even reach rather than how it's spelled."""
    source = inspect.getsource(conversation)
    for forbidden in ("Session", "db.", "commit(", "sessionmaker"):
        assert forbidden not in source, f"conversation.py must not reference {forbidden}"


def test_the_module_imports_nothing_that_could_write():
    """Limit 2 enforced structurally. A substring scan for "commit" is a
    tripwire, not a guarantee -- getattr(m, "comm"+"it") defeats it. What
    actually holds this boundary is the import surface: Conversation
    proposes, so it has no reason to import a session, an engine, or a
    model client. Assert that directly, and the only way to add a write
    path is to add an import this test will see."""
    import ast
    import pathlib

    source = pathlib.Path(conversation.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    # "contracts" is `from .contracts import Proposal` -- a same-package
    # relative import (level=1), which ast reports with module="contracts",
    # not "app.engine.contracts". That one import is the record this agent
    # hands off; nothing else in the module imports anything.
    allowed = {"__future__", "contracts"}
    assert imported <= allowed, f"conversation.py imports beyond its boundary: {imported - allowed}"


def test_no_anchor_yields_an_empty_target_list_not_a_guess():
    p = route("these are all type F", [])
    assert p.target_item_ids == []
