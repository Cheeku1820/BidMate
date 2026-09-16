"""reprocess.py -- applying a note and re-running the engine without
discarding a person's judgment.

The approval-preserving merge itself now lives in `merge.py`, narrowed
to run one sheet at a time (Task 5) -- this module is a thin delegate
kept only so the `/reprocess` route and `test_reprocess.py` (the merge's
regression net) do not have to move in the same change. Deleted once
Task 9 retires the whole-payload route in favor of the per-sheet worker.

`_strip_takeoff_id` exists only in this interim module, never in
`merge.py`. `estimate_service.py` mints a fresh `uuid.uuid4().hex`
`takeoff_id` on every run (see its `takeoff_id = uuid.uuid4().hex`),
so a note re-run posted through this route never carries the same
`takeoff_id` twice -- `upsert_sheet_rows`' `(takeoff_id, page_index)`
match would miss every time, and every re-run would insert a duplicate
sheet and duplicate items rather than merging onto the last run's,
silently doubling totals and re-orphaning undo ids in the process.
Stripping `takeoff_id` here (never inside `merge.py` itself) makes
`upsert_sheet_rows` fall back to matching by `number`, exactly as the
whole-project merge always did before Task 5 -- the fallback is safe
specifically because this interim path only ever has one open document
per project. Once the read job (B2) lands and `takeoff_id` becomes a
real, stable document id, two different documents can each contain a
sheet numbered "E2.1"; a number fallback inside `merge.py` itself would
risk merging those two sheets together, which is exactly why the
brief's ruling keeps this stripping here rather than in the module the
worker will call directly.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.merge import merge_payload
from app.takeoff.models import Project


def _strip_takeoff_id(payload: dict) -> dict:
    """A shallow copy with every `takeoff_id` removed, top-level and per
    sheet -- never mutates the caller's payload dict in place."""
    stripped = dict(payload)
    stripped.pop("takeoff_id", None)
    stripped["sheets"] = [{**s, "takeoff_id": ""} for s in (payload.get("sheets") or [])]
    return stripped


def reprocess_takeoff(db: DbSession, *, actor: User, project: Project, payload: dict) -> dict:
    return merge_payload(db, actor=actor, project=project, payload=_strip_takeoff_id(payload))
