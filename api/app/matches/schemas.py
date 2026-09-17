"""The wire shape of a symbol match. Nothing here names a score, a
threshold, a dpi, a method, or a job (CLAUDE.md: processing internals
stop at the API boundary)."""
import uuid

from pydantic import BaseModel, Field

from app.takeoff.schemas import ItemOut


class MatchBoxIn(BaseModel):
    x: int = Field(ge=0, le=1000)
    y: int = Field(ge=0, le=750)
    w: int = Field(ge=4, le=1000)
    h: int = Field(ge=4, le=750)


class MatchItemsIn(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    symbol: str | None = None
    system: str | None = None
    not_sure: bool = False


class SymbolMatchOut(BaseModel):
    id: uuid.UUID
    sheet_id: uuid.UUID
    box: list[int]
    status: str
    count: int
    matches: list[list[int]]
    error: str


class MatchItemOut(BaseModel):
    """`version` is the project snapshot version (the same `ETag`-style
    hash string `_item_mutation_response()` in `takeoff/mutations.py`
    returns for approve/reject/unreject/edit/delete), not `Item.version`
    -- the client's `mutateItem()` (`src/lib/store/api.js`) reads
    `raw.version` expecting that project-wide string, and this endpoint
    is one more item mutation as far as the client is concerned."""

    label: str
    version: str
    item: ItemOut
