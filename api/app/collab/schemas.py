"""`PresenceOut` -- moved here from `app.takeoff.schemas` (where the Task
11 stub left it) because it is a `collab` concern, not a `takeoff` one: it
describes a reviewer's live position, not anything persisted in the
takeoff domain tables.

The design's structural rule is that dependencies point one direction.
`app.takeoff.snapshot` already imports `app.collab.service` at module
level (Task 11, to call `active_presence`/`presence_signal`), so `takeoff
-> collab` is already the established direction; `app.takeoff.schemas`
importing `PresenceOut` from here keeps every takeoff -> collab edge
pointing the same way rather than having the schema depend one way and
the service call depend the other. `app.collab.router` importing
`app.takeoff.router.load_project` (collab -> takeoff, at the router
layer, a different pair of modules) does not create a cycle with either
of these -- `app.takeoff.router` does not import anything from
`app.collab`.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

MODEL_CONFIG = {"from_attributes": True}


class PresenceOut(BaseModel):
    user_id: uuid.UUID
    name: str
    color: str
    sheet_id: uuid.UUID | None = None
    item_id: uuid.UUID | None = None
    seen_at: datetime

    model_config = MODEL_CONFIG
