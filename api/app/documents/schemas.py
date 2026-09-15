"""Wire shapes for documents. snake_case, like the takeoff schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

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
    doc_type: str

    @field_validator("doc_type")
    @classmethod
    def _closed_set(cls, v: str) -> str:
        if v not in DOC_TYPES:
            raise ValueError(f"doc_type must be one of {', '.join(DOC_TYPES)}")
        return v
