"""Shared before/after snapshot plumbing for `Item` and `Warning` rows.

This is pure structural knowledge -- how to read every mapped column off
an ORM object, and what Python type each snapshotted field decodes back
to -- with no opinion about *when* a snapshot should be taken or what a
caller does with it afterward. It has no dependency on review semantics
(approve/reject/edit rules live in `review.py`), which is what lets
`review.py`, `bulk.py`, and `scale.py` all depend on it without any of
them depending on each other for plumbing that isn't actually about
their own domain logic.

Previously this lived inside `review.py`, and `scale.py` imported the
private `_column_snapshot` from it directly -- shared plumbing sitting
in a module that also enforces the missing-information approval rule,
found by a caller that had nothing to do with that rule. Moving it here
is the fix, not a rename: a future caller (Task 10's undo, first among
them) reads this module, not a review-internal one.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect

from app.takeoff.models import ReviewStatus, WarningReason

# Field -> Python type for every value in an Item snapshot (delete_item's
# full-column snapshot plus its nested "warnings" list), so a caller that
# reconstructs prior item state -- Task 10's undo -- can call
# `actions.decode_snapshot(fields, ITEM_SNAPSHOT_TYPES)` instead of
# reverse-engineering ~20 columns' types from JSONB, which carries none.
# "warnings" decodes to `list` (left alone); decode each element with
# WARNING_SNAPSHOT_TYPES below -- they're already individually encoded.
ITEM_SNAPSHOT_TYPES: dict[str, type] = {
    "id": uuid.UUID,
    "project_id": uuid.UUID,
    "sheet_id": uuid.UUID,
    "symbol": str,
    "name": str,
    "description": str,
    "system": str,
    "category": str,
    "quantity": Decimal,
    "unit": str,
    "status": ReviewStatus,
    "approved_by_user_id": uuid.UUID,
    "approved_at": datetime,
    "rejected_by_user_id": uuid.UUID,
    "rejected_at": datetime,
    "x": int,
    "y": int,
    "path": list,
    "notes": str,
    "evidence": dict,
    "material_cost": Decimal,
    "labor_hours": Decimal,
    "labor_cost": Decimal,
    "total_cost": Decimal,
    "placements": list,
    "ai_confirmed": bool,
    "updated_at": datetime,
    "warnings": list,
}

# Counterpart for decoding one element of the nested "warnings" list.
# Keyed by Python attribute name ("where_"), not the "where" database
# column name -- see _column_snapshot()'s docstring for why that
# distinction matters here.
WARNING_SNAPSHOT_TYPES: dict[str, type] = {
    "id": uuid.UUID,
    "item_id": uuid.UUID,
    "sheet_id": uuid.UUID,
    "reason": WarningReason,
    "title": str,
    "found": str,
    "why": str,
    "fix": str,
    "where_": str,
}

# The key `before`/`after` nest a list of per-item snapshots under, for
# any action recording more than one item's state in a single row
# (`bulk.bulk_approve()`, `scale.set_scale()`). Lives here, not in either
# of those modules, because it was previously defined twice -- once in
# each -- and briefly drifted to mean two different payload shapes under
# the same name before being unified. A single definition both modules
# import means that can't happen again, and Task 10's undo (which reads
# this key from actions it did not write) has exactly one place to look.
ITEMS_SNAPSHOT_KEY = "items"


def _column_snapshot(obj) -> dict:
    """Snapshot every mapped column of `obj`, keyed by Python attribute
    name, not database column name. They match for `Item`, but
    `Warning.where_` sits on the db column `"where"` (a reserved word) --
    keying by db column name would produce a `"where"` entry that
    neither `getattr`/`setattr` on the ORM object can use.
    """
    mapper = sa_inspect(type(obj))
    return {attr.key: getattr(obj, attr.key) for attr in mapper.column_attrs}
