"""The wire shape for the ROM estimate.

snake_case on the wire, like `ScheduleOut` and `LaborRowOut`. Nothing
here names how any number was produced beyond the basis vocabulary
itself: no confidence, no model, no run id, no processing stage
(ROADMAP invariant 7). `basis` is the deliberate exception and is not an
internal -- it is the one fact that makes an assumed number checkable,
it is written for an estimator and a GC to read, and its words come
from `app.estimate.basis.BASIS`'s labels.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.takeoff.schemas import MODEL_CONFIG


class EstimateLineOut(BaseModel):
    """One row of one section.

    `origin` is `counted` or `assumed` and is a separate axis from the
    four review labels -- a ROM has no approval step, so none of
    "Ready to review", "Needs attention", "Missing information", or
    "Estimator approved" appears anywhere in this shape.

    `amount` is None, never zero, for a line nothing could price. A line
    an estimator priced at zero carries `Decimal("0")`. The two render
    differently and must stay distinguishable on the wire.
    """

    id: uuid.UUID | None = None
    title: str
    origin: str                    # "counted" | "assumed"
    basis: str | None = None       # app.estimate.basis.BASIS key
    basis_label: str | None = None
    where: str = ""
    found: str | None = None
    why: str | None = None
    value: str | None = None
    unit: str | None = None
    amount: Decimal | None = None
    source: str | None = None      # "engine" | "estimator", assumed lines only
    model_config = MODEL_CONFIG


class AssumptionOverrideIn(BaseModel):
    """What the estimator typed over an assumed number.

    `unit` is optional and `None` means "leave it as it was" -- an
    estimator correcting a ceiling height from 14 to 16 should not have
    to retype "ft". Clearing a unit is not offered: the shape has no way
    to distinguish it from "unchanged", and a unit is a property of the
    quantity rather than something that goes away.
    """

    value: str
    unit: str | None = None


class EstimateSectionOut(BaseModel):
    key: str                       # app.estimate.basis.SECTIONS
    label: str
    counted_count: int
    assumed_count: int
    subtotal: Decimal | None = None
    lines: list[EstimateLineOut]
    model_config = MODEL_CONFIG


class QualificationOut(BaseModel):
    """One line of the condition of the price.

    Generated from the assumed lines above it, never typed separately --
    a qualifications block that can disagree with the sections it
    summarizes is worse than none, because it is the part a GC reads.
    """

    title: str
    found: str
    why: str
    where: str
    basis_label: str
    excluded_value: Decimal | None = None
    model_config = MODEL_CONFIG


class RangeOut(BaseModel):
    low: Decimal
    high: Decimal
    spread: Decimal
    model_config = MODEL_CONFIG


class EstimateOut(BaseModel):
    project_name: str
    revision_set_label: str
    sheet_count: int
    direct_cost: Decimal
    range: RangeOut
    counted_count: int
    assumed_count: int
    unpriced_count: int
    excluded_value: Decimal
    sections: list[EstimateSectionOut]
    qualifications: list[QualificationOut]
    # Set when there is nothing to estimate, with the reason. A bare $0
    # and a $0 that says why are different documents, and only one of
    # them is honest.
    empty_reason: str | None = None
    model_config = MODEL_CONFIG
