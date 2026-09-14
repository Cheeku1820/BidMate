"""Every vector set in the corpus, against a hand-written answer key.

The fixture under tests/fixtures/sheets/ was written by reading each
title block, not by running the engine -- a wrong engine cannot write
its own key. Counting is tested, not trained (CLAUDE.md).

Fixture conventions (see each file's "read_from"):
- a page with an empty "number" is a sheet whose title block cannot be
  read as text (TSC Nutrition's electrical pages carry no text layer --
  the text is outlined to paths); the key asserts it IS detected, with
  no number and a non-empty unreadable_reason, and its "kind" is the
  person's reading for the record, not asserted. A page that is not a
  sheet at all (a cover, a text-only page, another discipline) is simply
  not listed, and the key asserts it is not detected;
- "known_duplicate" on the second of two pages that genuinely carry the
  same number keeps a revision reissue a recorded fact, not a failure;
- an optional top-level "known_non_electrical" list names pages whose
  title-block number is in the E family but which are another
  discipline's sheet (spec 2.8 puts discipline beyond the family out of
  scope); they are neither "missed" nor "extra". No set needs it today.
"""

import json
import os
from pathlib import Path

import pymupdf
import pytest

from tests.bid_set import RASTER_SETS, VECTOR_SETS, corpus_path

FIXTURES = Path(__file__).parent / "fixtures" / "sheets"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _skip_unless(rel):
    if not os.path.exists(corpus_path(rel)):
        pytest.skip(f"corpus set not present: {rel}")


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_detected_pages_match_the_key(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    found = {s.page_index: s for s in documents.detect_sheets(corpus_path(fx["pdf"]))}
    expected = {s["page_index"]: s for s in fx["sheets"]}
    tolerated = set(fx.get("known_non_electrical", []))
    missed = sorted(set(expected) - set(found) - tolerated)
    extra = sorted(set(found) - set(expected) - tolerated)
    assert not missed, f"{name}: electrical pages not detected: {[(p, expected[p]['number'] or 'unreadable') for p in missed]}"
    assert not extra, f"{name}: non-electrical pages detected: {[(p, found[p].number) for p in extra]}"
    for p, s in expected.items():
        if p in tolerated:
            continue  # listed for the record; may or may not be detected
        if not s["number"]:
            assert found[p].number == "" and found[p].unreadable_reason, (name, p, found[p].number, found[p].unreadable_reason)
        else:
            assert not found[p].unreadable_reason, (name, p, found[p].unreadable_reason)


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_numbers_and_kinds_match_the_key(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    found = {s.page_index: s for s in documents.detect_sheets(corpus_path(fx["pdf"]))}
    for s in fx["sheets"]:
        if not s["number"]:
            continue
        got = found[s["page_index"]]
        assert got.number == s["number"], (name, s["page_index"], got.number, s["number"])
        assert got.kind == s["kind"], (name, s["page_index"], got.title, got.kind, s["kind"])


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_numbers_are_distinct_unless_the_key_says_otherwise(name):
    from app.engine import documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    dups = {s["page_index"] for s in fx["sheets"] if s.get("known_duplicate")}
    # Unreadable sheets carry no number and are not numbers to compare.
    numbers = [s.number for s in documents.detect_sheets(corpus_path(fx["pdf"])) if s.number and s.page_index not in dups]
    assert len(numbers) == len(set(numbers)), sorted(n for n in numbers if numbers.count(n) > 1)


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_every_placement_is_inside_its_visual_page(name):
    from app.engine import counting, documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    path = corpus_path(fx["pdf"])
    doc = pymupdf.open(path)
    for s in documents.detect_sheets(path):
        assert doc[s.page_index].rotation == next(f["rotation"] for f in fx["sheets"] if f["page_index"] == s.page_index)
        for c in counting.count_sheet(path, s):
            for p in c.placements:
                assert 0 <= p.x <= s.width_pt and 0 <= p.y <= s.height_pt, (name, s.number, p)


@pytest.mark.parametrize("name", sorted(VECTOR_SETS))
def test_non_plans_carry_no_devices(name):
    from app.engine import counting, documents

    fx = _fixture(name)
    _skip_unless(fx["pdf"])
    path = corpus_path(fx["pdf"])
    for s in documents.detect_sheets(path):
        if s.kind != "plan":
            assert counting.count_sheet(path, s) == [], (name, s.number, s.kind)


@pytest.mark.parametrize("name", sorted(RASTER_SETS))
def test_raster_sets_are_unreadable_not_silent(name):
    """A scanned set is detected AND unreadable. Zero sheets would read
    as "nothing electrical here" -- silence reads as completeness."""
    from app.engine import counting, documents

    rel = RASTER_SETS[name]
    _skip_unless(rel)
    path = corpus_path(rel)
    sheets = documents.detect_sheets(path)
    assert sheets, f"{name}: a raster set must surface its pages as unreadable, not vanish"
    for s in sheets:
        assert s.unreadable_reason, (name, s.page_index)
        assert counting.count_sheet(path, s) == []
