"""The wire shapes of the conversation panel.

`SCREEN_NAMES` is mirrored, verbatim, by src/components/conversation/
screenContext.js. The server never parses a URL: the client names the
screen from its own route table and the server refuses anything outside
this set. Nothing here names a model, a confidence, or an assistant."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SCREEN_NAMES = (
    "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
    "notes", "labor", "pricing", "export", "settings",
)

ScreenName = Literal[
    "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
    "notes", "labor", "pricing", "export", "settings",
]

# The four review labels the spreadsheet filters by; the server counts a
# status filter itself because status is a column. A search string is
# only named, never re-implemented.
STATUS_FILTERS = ("ready", "attention", "missing", "approved")


class ViewIn(BaseModel):
    filter: Literal["ready", "attention", "missing", "approved"] | None = None
    search: str | None = Field(default=None, max_length=200)


class ScreenIn(BaseModel):
    name: ScreenName
    sheet_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    view: ViewIn | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    screen: ScreenIn


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    text: str
    screen: dict | None
    created_at: datetime


class ConversationOut(BaseModel):
    messages: list[MessageOut]
