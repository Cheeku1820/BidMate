import uuid

from sqlalchemy.orm import Session as DbSession

from app.identity.models import User
from app.takeoff.models import Action


def commit(
    db: DbSession,
    *,
    actor: User,
    project_id: uuid.UUID,
    kind: str,
    label: str,
    before: dict,
    after: dict,
    item_id: uuid.UUID | None = None,
    sheet_id: uuid.UUID | None = None,
    undoes_action_id: uuid.UUID | None = None,
) -> Action:
    """The only way anything in this module records a change.

    Every mutation routes through here so attribution and the audit trail
    cannot be forgotten by a future endpoint.
    """
    action = Action(
        project_id=project_id, kind=kind, label=label, before=before, after=after,
        item_id=item_id, sheet_id=sheet_id, actor_user_id=actor.id, undoes_action_id=undoes_action_id,
    )
    db.add(action)
    return action
