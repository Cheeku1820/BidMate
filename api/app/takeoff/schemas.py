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
    # The optimistic-concurrency counter (task-13b-brief.md): the client
    # sends this back on its next single-item mutation so a stale write
    # is refused rather than silently clobbering a concurrent change. A
    # plain int, not a Decimal-as-string -- this is a row generation
    # counter, not a bid quantity, and has no rounding or precision
    # concern the string-wire-format decision (decision 1, Task 13) was
    # protecting against.
    version: int
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


# --- Mutation response models (Task 13) ---
#
# Every mutation endpoint returns one of the models below rather than a
# bare `{"label": ...}` dict -- task-13-brief.md, decision 3. The design
# doc's client-port section is explicit that writes are not optimistic:
# "the response carries updated state plus the action, and the client
# renders that." A bare label leaves the client waiting on the next poll
# (up to a few seconds) to see its own write land, and DESIGN.md's
# autosave rhythm (Saving... -> Saved 2:41 PM) is built on the response
# being authoritative.
#
# Two shapes, not one, because "updated state" means something different
# depending on how many rows a mutation can touch:
#
# - A single-item mutation (approve/reject/unreject/edit/delete) returns
#   `ItemMutationOut`: the label, the new version, and the one item that
#   changed. Sending a whole snapshot back for a one-row change would be
#   needless payload on the hottest write paths in the app.
# - bulk-approve, scale, undo, and redo can each touch many rows in one
#   action, and `snapshot.build()` already exists as the one shape the
#   client renders -- reusing it here (`BulkApproveOut.snapshot`,
#   `ScaleMutationOut.snapshot`, `UndoRedoOut.snapshot`) is simpler and
#   provably consistent with what a poll would return, rather than
#   inventing a second, narrower "what changed" shape for each of them.
#
# Every one of these carries (or embeds, via `snapshot.version`) the new
# version string: without it, the client's very next poll could send the
# ETag it already had and get a 304 against state it has not seen yet.


class ItemMutationOut(BaseModel):
    """Response for approve, reject, unreject, edit, and delete.

    `item` is `None` only for delete, where there is no longer a row to
    describe -- `label` and `version` still say what happened and let the
    client's next poll stay in sync. Every other mutation returns the
    item exactly as it now stands, so the client can render it
    immediately instead of waiting for the next poll to catch up.
    """

    label: str
    version: str
    item: ItemOut | None = None


class SkippedItemOut(BaseModel):
    """One bulk-approve item that did not move, with the estimator-facing
    copy for why (task-13-brief.md, decision 4) -- carried forward from
    Task 8's note that the skip codes ("not_in_project", "rejected",
    "already_approved", "needs_attention", "missing_information") had no
    recovery copy yet. `needs_attention` and `missing_information` are
    two codes, not the single "not_ready_to_review" this shipped with
    initially -- a review finding that collapsing them lost the
    distinction CLAUDE.md's status vocabulary treats as the spine: one is
    a resolvable judgment call, the other is blocked with no override.
    `code` travels alongside `message` so the client can branch on it
    (grouping skipped items by reason, say) without parsing English, and
    so the wording lives in exactly one place (`mutations._SKIP_COPY`)
    rather than being re-invented per screen.
    """

    item_id: uuid.UUID
    code: str
    message: str


class BulkApproveOut(BaseModel):
    approved: list[uuid.UUID]
    skipped: list[SkippedItemOut]
    snapshot: SnapshotOut


class ScaleMutationOut(BaseModel):
    label: str
    snapshot: SnapshotOut


class UndoRedoOut(BaseModel):
    """`performed` lets the client tell "nothing to undo" from "undone"
    without inspecting a null label (task-13-brief.md, "Also required":
    the sketch's `{"label": None}` with a 200 status makes those two
    outcomes indistinguishable without a special-cased null check).
    `label` and `snapshot` are populated only when `performed` is true;
    there is nothing new for either to describe otherwise.
    """

    performed: bool
    label: str | None = None
    snapshot: SnapshotOut | None = None
