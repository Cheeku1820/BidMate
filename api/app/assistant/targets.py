"""Which rows a panel sentence would change.

The router names a *form* -- the selection, the view, a tag -- and this
resolves it here, server-side, through the same predicates the screens
themselves read from (`totals.countable_items`, `resolve.targets_for`).
No id the model produced is ever trusted, and nothing outside what the
estimator could have reached with a filter is ever a target.

The cap is the other half of that rule: past MAX_TARGETS the proposal
is refused with copy rather than offered. A bulk change that large
belongs in a form, where the list is on screen.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DbSession

from app.assistant.schemas import ScreenIn
from app.engine.conversation import RouteTargets
from app.takeoff.models import Item, Project, ReviewStatus
from app.takeoff.resolve import targets_for
from app.takeoff.totals import countable_items

MAX_TARGETS = 50

_STATUS = {"ready": ReviewStatus.READY, "attention": ReviewStatus.ATTENTION,
           "missing": ReviewStatus.MISSING, "approved": ReviewStatus.APPROVED}


class TooMany(Exception):
    """More rows than a card can honestly preview."""

    def __init__(self, count: int):
        self.count = count
        super().__init__(f"{count} targets")


def _like(column, needle: str):
    return func.lower(func.coalesce(column, "")).like(needle)


def _view_query(project: Project, screen: ScreenIn):
    query = countable_items(project.id)
    if screen.sheet_id is not None:
        query = query.where(Item.sheet_id == screen.sheet_id)
    view = screen.view
    if view is not None and view.filter:
        query = query.where(Item.status == _STATUS[view.filter])
    if view is not None and view.search:
        needle = f"%{view.search.strip().lower()}%"
        query = query.where(or_(_like(Item.name, needle), _like(Item.description, needle),
                                _like(Item.source_tag, needle)))
    return query.order_by(Item.id)


def resolve_items(db: DbSession, project: Project, targets: RouteTargets, screen: ScreenIn) -> list[Item]:
    if targets.form == "selection":
        if screen.item_id is None:
            return []
        item = db.get(Item, screen.item_id)
        if item is None or item.project_id != project.id:
            return []
        rows = targets_for(db, item, cluster=True)
    elif targets.form == "view":
        rows = list(db.scalars(_view_query(project, screen)))
    elif targets.form == "tag":
        needle = targets.tag.strip().lower()
        if not needle:
            return []
        query = countable_items(project.id)
        if screen.sheet_id is not None:
            query = query.where(Item.sheet_id == screen.sheet_id)
        rows = list(db.scalars(
            query.where(or_(func.lower(func.coalesce(Item.source_tag, "")) == needle,
                            _like(Item.name, f"%{needle}%"))).order_by(Item.id)))
    else:
        return []
    if len(rows) > MAX_TARGETS:
        raise TooMany(len(rows))
    return rows


def anchor_of(items: list[Item], *, selected_id: uuid.UUID | None) -> Item | None:
    """The item a reclassify reads from: the estimator's selection when
    it is in the set, so the reading is about what they are looking at,
    and otherwise the first."""
    if not items:
        return None
    for item in items:
        if selected_id is not None and item.id == selected_id:
            return item
    return items[0]
