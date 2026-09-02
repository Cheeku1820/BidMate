"""Frozen eval set for grounded classification warnings
(docs/superpowers/specs/2026-09-01-grounded-classification-warnings-design.md,
section D). Fixed inputs -- a score change on a prompt edit is
attributable to the prompt, not to different test data. Extend this list
once real design-partner drawing sets exist (BUILD-STAGES.md's "frozen
eval set per agent"); for now it mirrors the fixtures already exercised
in api/tests/test_engine_classify.py.
"""

CASES = [
    {
        "id": "unlisted-fixture-letter",
        "tags": [{"tag": "F2", "count": 3}, {"tag": "R", "count": 40}],
        "schedule_text": "LUMINAIRE SCHEDULE\nTYPE A - 2x4 LED TROFFER\nTYPE B - LED HIGH BAY\nTYPE C - EXIT SIGN",
        "location": "Sacramento, CA",
    },
    {
        "id": "unrecognized-tag",
        "tags": [{"tag": "Z9", "count": 4}],
        "schedule_text": "",
        "location": "Chicago, IL",
    },
    {
        "id": "recognized-device-no-warning-expected",
        "tags": [{"tag": "R", "count": 22}],
        "schedule_text": "",
        "location": "Denver, CO",
        # The one case whose expectation is the ABSENCE of a warning; the
        # runner reports a mismatch rather than silently skipping it.
        "expect_warning": False,
    },
    {
        "id": "fixture-letter-in-schedule",
        "tags": [{"tag": "A", "count": 18}],
        "schedule_text": "LUMINAIRE SCHEDULE\nTYPE A - 2x4 LED TROFFER, 3500 LUMEN",
        "location": "Austin, TX",
    },
]
