"""Wire shapes for documents. snake_case, like the takeoff schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

DOC_TYPES = ("Drawings", "Specifications", "Addendum", "Scope", "Other")
DOC_STATUSES = ("uploaded", "processing", "processed", "failed")


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    filename: str
    doc_type: str
    size_bytes: int
    sha256: str
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
