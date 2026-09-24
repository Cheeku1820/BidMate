"""Every estimator-facing sentence a proposal card can carry. One place,
so the register stays a knowledgeable colleague's: sentence case, no
exclamation marks, and no mention of how the reading was made."""

from __future__ import annotations


def item_note() -> str:
    return "Approving stays with you."


def reclassify(count: int, name: str, sheet: str) -> str:
    items = "item" if count == 1 else "items"
    where = f" on {sheet}" if sheet else ""
    return f"Name {count} {items}{where} {name}."


def exclude(count: int, sheet: str) -> str:
    items = "item" if count == 1 else "items"
    where = f" on {sheet}" if sheet else ""
    return f"Take {count} {items}{where} out of the takeoff, with your words as the reason."


def note(title: str) -> str:
    return f"Add a note to this project: {title}"


def scope_status(status: str, text: str) -> str:
    word = {"confirmed": "Confirm", "dismissed": "Dismiss", "found": "Reopen"}[status]
    return f"{word} this scope statement: {text}"


def scope_text(text: str) -> str:
    return f"Reword this scope statement to: {text}"


def plan_status(status: str, text: str) -> str:
    word = {"confirmed": "Confirm", "dismissed": "Dismiss", "found": "Reopen"}[status]
    return f"{word} this line on the project plan: {text}"


def plan_text(text: str) -> str:
    return f"Reword this line on the project plan to: {text}"


def plan_answer(title: str) -> str:
    return f"Answer the open question \"{title}\" and save it as a note."


def others_left_out(count: int) -> str:
    items = "item" if count == 1 else "items"
    return f" {count} other matching {items} sit outside this cluster; say so again with one of them selected to change those."


def too_many(count: int) -> str:
    return f"That would change {count} items. Narrow it down — filter the view, or pick a sheet."
