"""Wire shapes for documents. snake_case, like the takeoff schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

DOC_TYPES = ("Drawings", "Specifications", "Addendum", "Scope", "Other", "Pricing")
# The closed set `documents.status` is constrained to, in the database
# (migration 0020's `ck_documents_status`) as well as here. B1 only ever
# writes 'uploaded'; the other three are the worker's from B2 on, and
# the constraint is what stops that writer inventing a fifth.
DOC_STATUSES = ("uploaded", "processing", "processed", "failed")


class DocumentOut(BaseModel):
    """No `sha256`. Nothing in the interface reads it, and spec §7 keeps
    "hash" out of anything estimator-facing -- a field on the wire is one
    copy change away from being rendered. The duplicate rule it backs
    speaks in filenames instead ("the same file as first.pdf, uploaded
    earlier")."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    doc_type: str
    size_bytes: int
    status: str
    error: str
    created_at: datetime


class DocumentTypeIn(BaseModel):
    """Deliberately unvalidated against `DOC_TYPES` here: the estimator-
    facing rejection ("Document type must be one of ...") is
    `service.set_doc_type`'s to raise, in the same sentence-case wording
    `store_upload` already uses. A field validator's message is field-
    name-first pydantic phrasing ("doc_type must be one of ..."), and
    letting two call sites each own a version of this message is how
    they drift -- the service is the single gate."""

    doc_type: str
