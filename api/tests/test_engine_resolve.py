"""The estimator's sentence -> a proposal (say-what-it-is spec, 'The
resolve service' steps 3-5). The model is stubbed; what is tested is the
retrieval, the fallback, and that a stub answer is passed through."""
import pytest

from app.engine import resolve
from app.engine.catalog import CATALOG


def test_leading_count_is_read_from_the_front_of_the_sentence():
    assert resolve.leading_count("28 of these, the two by the dock are existing") == 28
    assert resolve.leading_count("2x4 LED troffer, type F") is None   # "2x4" is a size, not a count
    assert resolve.leading_count("12 duplex receptacles") == 12
    assert resolve.leading_count("") is None


def test_typed_fallback_uses_the_words_and_never_a_catalog_id():
    p = resolve.typed_fallback("28 patient headwalls, 4-gang")
    assert p["source"] == "typed"
    assert p["name"] == "patient headwalls, 4-gang"
    assert p["quantity"] == 28
    assert p["catalog_id"] is None and p["schedule_match"] is None
    assert p["system"] == "Unknown" and p["category"] == "Unclassified"
    assert p["summary"] == "Read from your words as a custom item."


def test_candidates_are_ranked_by_token_overlap_and_capped_at_five():
    out = resolve.candidates("20A duplex receptacle in the office", CATALOG, [])
    assert out and out[0]["name"].lower().startswith("20a duplex")
    assert len(out) <= 5
    assert {"id", "name", "system", "category"} <= set(out[0])


def test_a_resolution_for_the_same_tag_ranks_first():
    resolutions = [{"id": "res-1", "tag": "F", "name": "2x4 LED troffer, 4000K", "system": "Lighting", "category": "Fixtures"}]
    out = resolve.candidates("some fixture", CATALOG, resolutions, tag_hint="F")
    assert out[0]["id"] == "res-1"


def test_resolve_falls_back_when_no_key(monkeypatch):
    monkeypatch.setattr(resolve.llm, "available", lambda: False)
    p = resolve.resolve("2x4 LED troffer", {"tag": "F", "count": 30, "sheet": "EP101"}, [], "")
    assert p["source"] == "typed" and p["name"] == "2x4 LED troffer"


def test_resolve_falls_back_when_the_call_fails(monkeypatch):
    monkeypatch.setattr(resolve.llm, "available", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("transport")
    monkeypatch.setattr(resolve.llm, "resolve_proposal", boom)
    p = resolve.resolve("2x4 LED troffer", {"tag": "F", "count": 30, "sheet": "EP101"}, [], "")
    assert p["source"] == "typed"


def test_resolve_passes_a_stubbed_proposal_through(monkeypatch):
    monkeypatch.setattr(resolve.llm, "available", lambda: True)
    monkeypatch.setattr(resolve.llm, "resolve_proposal", lambda *a, **k: {
        "name": "2x4 LED troffer, 4000K — type F", "system": "Lighting", "category": "Fixtures", "unit": "ea",
        "catalog_id": "luminaire_troffer", "schedule_match": {"sheet": "E-501", "line": "F"},
        "quantity": None, "summary": "Applies to all 30 · renames Luminaire type F · clears the warning",
    })
    p = resolve.resolve("2x4 LED troffer, type F on E-501", {"tag": "F", "count": 30, "sheet": "EP101"}, [], "")
    assert p["source"] == "read" and p["catalog_id"] == "luminaire_troffer"
    assert p["schedule_match"] == {"sheet": "E-501", "line": "F"}


def test_a_malformed_stub_answer_falls_back(monkeypatch):
    monkeypatch.setattr(resolve.llm, "available", lambda: True)
    monkeypatch.setattr(resolve.llm, "resolve_proposal", lambda *a, **k: {"name": ""})  # missing fields
    p = resolve.resolve("2x4 LED troffer", {"tag": "F", "count": 30, "sheet": "EP101"}, [], "")
    assert p["source"] == "typed"
