"""upsert_evidence_image -- the one function both first-time ingest
(ingest_service.py) and a reprocess re-run (reprocess.py) call to keep an
item's evidence image in sync with what the engine most recently produced
for it. Split out rather than living in either caller: both need the
exact same replace-or-clear behavior, and ingest.py's mapping stays a
pure function (its own docstring's stated contract) by not touching the
database itself.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session as DbSession

from app.takeoff.models import ItemEvidenceImage


def upsert_evidence_image(db: DbSession, item_id: uuid.UUID, png: bytes | None) -> None:
    """Replace item_id's evidence image, or clear it if `png` is None.

    Always deletes whatever existed first: a re-run whose crop failed
    this time must not leave a previous run's image standing in for a
    takeoff it no longer matches.
    """
    db.query(ItemEvidenceImage).filter_by(item_id=item_id).delete()
    if png is not None:
        db.add(ItemEvidenceImage(item_id=item_id, png=png))
