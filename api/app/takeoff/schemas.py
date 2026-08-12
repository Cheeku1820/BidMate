"""Explicit Pydantic response models for the read endpoints.

ORM objects are never returned directly, and none of the builder functions
in `snapshot.py` construct these with `**obj.__dict__` -- a mapped object's
`__dict__` holds only currently-loaded attributes and carries SQLAlchemy's
own `_sa_instance_state`; after a commit (or any other expiry) it can be
empty or partial, producing a `ValidationError` on a required field rather
than the lazy load a plain attribute access would trigger. Every builder in
`snapshot.py` instead passes explicit keyword arguments read off the ORM
object with ordinary attribute access, which is also where the fields with
no direct column counterpart get computed: `status` (enum -> its `.value`),
`rejected` (`rejected_at is not None`), `superseded` (`superseded_at is not
None`), a warning's `where` (`Warning.where_`, since `where` is a reserved
SQL keyword the column can't be named), and `approved_by` (the approving
user's display name, not their id).
"""

import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.collab.schemas import PresenceOut

MODEL_CONFIG = {"from_attributes": True}


class WarningOut(BaseModel):
    # A specific warning's own id, not just the item's -- Task 13's
    # mutation endpoints (resolving one warning among an item's several)
    # need to address a particular row, and there is no other stable
    # handle for one once an item can carry more than one of these (see
    # `warnings` below).
    id: uuid.UUID
    title: str
    found: str
    why: str
    fix: str
    where: str
    # A domain fact, not a processing internal -- lets the client tell a
    # scale-blocked item from a legend-blocked one without inventing a
    # fifth status. Serialized as the enum's string value ("scale",
    # "legend"), the same convention `status` below follows.
    reason: str

    model_config = MODEL_CONFIG


class ItemOut(BaseModel):
    id: uuid.UUID
    sheet_id: uuid.UUID
    symbol: str
    name: str
    description: str
    system: str
    category: str
    quantity: Decimal
    unit: str
    status: str
    approved_by: str | None = None
    rejected: bool = False
    x: int | None = None
    y: int | None = None
    path: list | None = None
    notes: str
    evidence: dict | None = None
    # A list, not a single optional warning: an item can carry more than
    # one live warning at once (Task 9's scale-and-legend case is the
    # concrete example, exercised in tests/test_undo_redo.py), and a
    # singular field can only ever show one, non-deterministically,
    # depending on unordered query return order. Sorted by (reason, id) in
    # snapshot.py's query so the order is stable across polls.
    warnings: list[WarningOut] = Field(default_factory=list)

    model_config = MODEL_CONFIG


class SheetOut(BaseModel):
    id: uuid.UUID
    number: str
    title: str
    discipline: str
    revision: str
    scale: str
    scale_options: list[str]
    plan: str
    superseded: bool = False

    model_config = MODEL_CONFIG


class ProjectOut(BaseModel):
    """The row shape for `GET /projects` -- a project list, not a project's
    full detail."""

    id: uuid.UUID
    name: str
    revision_set_label: str

    model_config = MODEL_CONFIG


class ProjectDetailOut(BaseModel):
    """`GET /projects/{id}` -- the project plus its sheets, which is where
    each sheet's scale state (`scale`, `scale_options`, `superseded`)
    lives. Listed in the Task 11 plan's "Produces" and the design's API
    surface, but no step in the plan's sketch actually built it.
    """

    id: uuid.UUID
    name: str
    revision_set_label: str
    sheets: list[SheetOut]

    model_config = MODEL_CONFIG


class UndoOut(BaseModel):
    can_undo: bool
    can_redo: bool
    undo_label: str | None = None
    undo_by: str | None = None
    redo_label: str | None = None


class TotalsOut(BaseModel):
    by_system: dict[str, Decimal]
    approved_count: int
    remaining_count: int
    attention_count: int
    missing_count: int
    approved_units: Decimal


class SnapshotOut(BaseModel):
    version: str
    sheets: list[SheetOut]
    items: list[ItemOut]
    totals: TotalsOut
    undo: UndoOut
    presence: list[PresenceOut]
