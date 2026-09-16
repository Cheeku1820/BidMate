"""reprocess.py -- applying a note and re-running the engine without
discarding a person's judgment.

The approval-preserving merge itself now lives in `merge.py`, narrowed
to run one sheet at a time (Task 5) -- this module is a thin delegate
kept only so the `/reprocess` route and `test_reprocess.py` (the merge's
regression net) do not have to move in the same change. Deleted once
Task 9 retires the whole-payload route in favor of the per-sheet worker.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.merge import merge_payload
from app.takeoff.models import Project


def reprocess_takeoff(db: DbSession, *, actor: User, project: Project, payload: dict) -> dict:
    return merge_payload(db, actor=actor, project=project, payload=payload)
