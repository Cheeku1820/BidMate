"""app/assistant/context.py -- what each screen puts in view. The
screen name is a closed set mirrored by src/components/conversation/
screenContext.js; a name outside it is a validation error, never a
guess."""
import uuid

import pytest
from pydantic import ValidationError

from app.assistant.schemas import SCREEN_NAMES, ScreenIn


def test_screen_names_are_the_closed_set():
    assert SCREEN_NAMES == (
        "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
        "notes", "labor", "pricing", "export", "settings",
    )


def test_screen_outside_the_set_is_refused():
    with pytest.raises(ValidationError):
        ScreenIn(name="dashboard")
    screen = ScreenIn(name="spreadsheet", sheet_id=uuid.uuid4(), view={"filter": "attention"})
    assert screen.view.filter == "attention"
    assert screen.item_id is None
