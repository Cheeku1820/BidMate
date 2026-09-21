"""What this firm already said a tag is, applied to a later run's rows
before they merge (say-what-it-is spec). A resolved tag arrives named,
at Ready to review, with no warning -- and never approved: the run does
not know whether this set's F is last time's F, only that a person once
said so, and the estimator confirms it again with one key."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import SymbolResolution


def overlay(db: DbSession, project_id: uuid.UUID, rows: list[dict]) -> int:
    by_tag = {r.tag: r for r in db.scalars(select(SymbolResolution).where(SymbolResolution.project_id == project_id))}
    if not by_tag:
        return 0
    changed = 0
    for row in rows:
        res = by_tag.get(row.get("source_tag") or "")
        if res is None:
            continue
        row["name"], row["system"], row["category"] = res.name, res.system, res.category
        if row.get("status") != "approved":
            row["status"] = "ready"
        row["warning"] = None
        row["description"] = f"Read as {res.name} from your earlier review."
        changed += 1
    return changed
