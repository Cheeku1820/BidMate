"""Seed command: loads the prototype's twelve-item demo takeoff
(src/lib/data.js) into a real database project, "Meridian Distribution
Center," so the ported review workspace (Task 15) has something to
render against a real API instead of localStorage.

This is a fixture, not an engine -- see docs/superpowers/specs/2026-08-07
-backend-spine-design.md, "Out of scope." Nothing here simulates
document processing; the data below is transcribed by hand from
src/lib/data.js and written directly.

**Trivially removable.** That was a scoping condition on this slice, and
it holds: this module imports only from app.db, app.identity.models,
app.takeoff.models, and app.auth.passwords -- ordinary application
modules every other part of the codebase already depends on. Nothing
outside this file and its test (tests/test_seed.py) imports anything
from it. Deleting seed mode later is deleting these two files; no other
module has a reference to remove.

**Idempotent, keyed deterministically.** Every row this module writes
gets a `uuid.uuid5` id derived from a fixed namespace plus that row's own
identity in data.js -- "org", "project", "sheet:E2.1", "item:it-04",
"warning:it-04", and so on. `run()` looks up `PROJECT_ID` first and
returns immediately if it already exists, so a second run performs zero
writes rather than a second, differently-keyed copy of the fixture (or,
worse, a half-written one from an interrupted first run landing
alongside a second attempt). The email-keyed user id is the one
exception: it is derived from the *credential's* email rather than a
fixed literal, since the email itself comes from the environment, not
from data.js.

**A fixture, not history.** Every row is added directly with `db.add()`
-- never through `app.takeoff.actions.commit()` -- so seeding writes no
`Action` row and none of it appears in the undo stack. Undoing a seed
approval would be undoing something no estimator actually did.

**No default password.** `run()` takes credentials as arguments rather
than reading the environment itself, so it stays a plain, testable
function; `main()` is the only thing that reads `SEED_EMAIL` /
`SEED_PASSWORD`, and it exits loudly (`SystemExit`, no baked-in
fallback) if either is unset. A default password in a seed script is
exactly how demo credentials end up live in a real deployment.

**BLOCKER, resolved via migration 0007** (see its docstring in
migrations/versions/0007_warning_reason_schedule_conflict.py for the
full reasoning): data.js's "Fixture type conflicts with the schedule"
warning matches neither `WarningReason.SCALE` nor `.LEGEND`. Tagging it
SCALE to make it fit would make `scale.set_scale()` silently delete it
the moment E2.1's scale is confirmed -- destroying evidence about a
fixture/schedule disagreement the estimator never saw. It is tagged
`WarningReason.SCHEDULE_CONFLICT`, a new, deliberately-named third
member of that closed vocabulary, not a catch-all. Every real warning
the takeoff engine (Track 2) eventually emits will need to classify
itself into one of these three reasons -- there is no default to fall
back to.
"""

import os
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session as DbSession

from app.auth.passwords import hash_password
from app.db import SessionLocal
from app.identity.models import Org, User
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason

# Fixed and arbitrary -- generated once (uuid.uuid4()) and never
# regenerated, since every id this module derives from it has to be
# stable across runs and across environments for idempotency to hold.
_SEED_NAMESPACE = uuid.UUID("fd195d93-1e85-4868-9300-bda658d12bc6")


def _seed_uuid(key: str) -> uuid.UUID:
    """A deterministic id for a fixture row, derived from its own
    identity in data.js rather than assigned by the database. Calling
    this twice with the same key always returns the same uuid, which is
    what lets `run()` treat "does PROJECT_ID already exist" as the
    entire idempotency check.
    """
    return uuid.uuid5(_SEED_NAMESPACE, key)


ORG_ID = _seed_uuid("org")
PROJECT_ID = _seed_uuid("project")

# A fixed, plausible approval timestamp for the two items data.js marks
# pre-approved -- data.js itself carries no timestamp, only an
# `approvedBy` name, so this is invented but constant across runs.
_APPROVED_AT = datetime(2026, 6, 5, 14, 30, tzinfo=timezone.utc)

STATUS_BY_KEY = {
    "ready": ReviewStatus.READY,
    "attention": ReviewStatus.ATTENTION,
    "missing": ReviewStatus.MISSING,
    "approved": ReviewStatus.APPROVED,
}

# See the BLOCKER note in the module docstring: this is the deliberate
# classification decision this task made, in one place, so a reviewer
# can see all four warnings' reasons at a glance rather than hunting
# through the item list below.
WARNING_REASON_BY_TITLE = {
    "Scale needs confirmation": WarningReason.SCALE,
    "Missing scale reference": WarningReason.SCALE,
    "Symbol is not in the legend": WarningReason.LEGEND,
    "Fixture type conflicts with the schedule": WarningReason.SCHEDULE_CONFLICT,
}

# Transcribed from src/lib/data.js's SHEETS, in the same order (which
# becomes sort_order below) -- ids are data.js's own sheet ids, used as
# the deterministic-uuid key and nowhere else.
SHEETS_DATA = [
    {"id": "E2.1", "number": "E2.1", "title": "Power plan — warehouse", "discipline": "Electrical",
     "revision": "Rev 2", "revision_date": "2026-05-14", "scale": "mixed",
     "scale_options": ['1/8" = 1\'-0"', '1/16" = 1\'-0"'], "plan": "warehouse"},
    {"id": "E1.1", "number": "E1.1", "title": "Lighting plan — first floor", "discipline": "Electrical",
     "revision": "Rev 3", "revision_date": "2026-06-02", "scale": "none",
     "scale_options": ['1/8" = 1\'-0"', '3/16" = 1\'-0"', '1/4" = 1\'-0"'], "plan": "office"},
    {"id": "E3.1", "number": "E3.1", "title": "Panel schedules and details", "discipline": "Electrical",
     "revision": "Rev 1", "revision_date": "2026-04-28", "scale": "nts", "scale_options": [], "plan": "schedule"},
]

# Transcribed from src/lib/data.js's ITEMS, verbatim -- same ids, names,
# quantities, systems, positions, warnings, and evidence. Point items
# carry x/y; the two conduit runs carry path instead, matching
# Item.x/Item.y/Item.path directly.
ITEMS_DATA = [
    {"id": "it-01", "sheet": "E2.1", "symbol": "panel", "name": "Panel LP-1",
     "description": "208Y/120V, 3-phase, 42-circuit, surface mounted at column B-2.",
     "system": "Distribution", "category": "Panels", "quantity": 1, "unit": "EA", "status": "approved",
     "x": 178, "y": 214, "evidence": {"sheet": "E2.1", "detail": "Panel tag at column B-2", "crop": "panel"}},
    {"id": "it-02", "sheet": "E2.1", "symbol": "run", "name": '2" EMT conduit run',
     "description": "Feeder from LP-1 to warehouse floor box circuit, routed above deck.",
     "system": "Power", "category": "Conduit and wire", "quantity": 184, "unit": "LF", "status": "missing",
     "path": [[186, 226], [186, 430], [402, 430], [402, 508]],
     "warning": {
         "title": "Scale needs confirmation",
         "found": "E2.1 shows two different scale labels — one in the title block and one under the "
                  "enlarged dock plan.",
         "why": "Measured conduit lengths on this sheet may be wrong until the plan scale is settled.",
         "fix": "Select the scale that applies to the warehouse plan, then re-check this run.",
         "where": "E2.1 title block and enlarged plan note",
     },
     "evidence": {"sheet": "E2.1", "detail": "Title block scale note", "crop": "titleblock"}},
    {"id": "it-03", "sheet": "E2.1", "symbol": "receptacle", "name": "20A duplex receptacle",
     "description": "Wall-mounted general purpose receptacle, +18\" AFF, warehouse perimeter.",
     "system": "Power", "category": "Devices", "quantity": 14, "unit": "EA", "status": "ready",
     "x": 556, "y": 508, "evidence": {"sheet": "E2.1", "detail": "Typical device tag, grid C-3", "crop": "device"}},
    {"id": "it-04", "sheet": "E2.1", "symbol": "highbay", "name": "High-bay LED fixture, type A",
     "description": "Pendant mounted high bay over open warehouse, 24'-0\" mounting height.",
     "system": "Lighting", "category": "Fixtures", "quantity": 26, "unit": "EA", "status": "attention",
     "x": 662, "y": 268,
     "warning": {
         "title": "Fixture type conflicts with the schedule",
         "found": "The plan tags this fixture as type A. The fixture schedule on E0.1 lists the same tag "
                  "as type A1 at a different wattage.",
         "why": "The two types carry different material cost and labor units, so the count would be "
                "priced against the wrong fixture.",
         "fix": "Confirm which type governs, then correct the classification before approving.",
         "where": "E2.1 plan tag and E0.1 luminaire schedule",
     },
     "evidence": {"sheet": "E0.1", "detail": "Luminaire schedule, rows A and A1", "crop": "schedule"}},
    {"id": "it-05", "sheet": "E2.1", "symbol": "disconnect", "name": "60A disconnect switch",
     "description": "Non-fused, NEMA 3R, exterior wall at loading dock, feeds dock leveler.",
     "system": "Power", "category": "Disconnects", "quantity": 2, "unit": "EA", "status": "ready",
     "x": 836, "y": 592, "evidence": {"sheet": "E2.1", "detail": "Dock equipment note", "crop": "device"}},
    {"id": "it-06", "sheet": "E2.1", "symbol": "exit", "name": "Exit sign, combination unit",
     "description": "LED exit and emergency light, ceiling mounted with 90-minute battery.",
     "system": "Life safety", "category": "Life safety", "quantity": 6, "unit": "EA", "status": "ready",
     "x": 470, "y": 138, "evidence": {"sheet": "E2.1", "detail": "Egress path note", "crop": "device"}},
    {"id": "it-07", "sheet": "E2.1", "symbol": "unknown", "name": "Unclassified symbol",
     "description": "A repeated symbol near the dock office was found but does not match the legend on "
                     "this set.",
     "system": "Power", "category": "Unclassified", "quantity": 3, "unit": "EA", "status": "attention",
     "x": 748, "y": 442,
     "warning": {
         "title": "Symbol is not in the legend",
         "found": "This symbol appears three times near the dock office and is not defined in the E0.1 "
                  "legend.",
         "why": "An unclassified item carries no material or labor, so it would be missing from the "
                "estimate.",
         "fix": "Identify the device and set its classification, or reject it if it belongs to another "
                "trade.",
         "where": "E2.1 dock office area and E0.1 symbol legend",
     },
     "evidence": {"sheet": "E0.1", "detail": "Symbol legend, electrical", "crop": "schedule"}},
    {"id": "it-08", "sheet": "E1.1", "symbol": "troffer", "name": "2x4 LED troffer, type F",
     "description": "Recessed lay-in troffer, open office and corridor ceiling grid.",
     "system": "Lighting", "category": "Fixtures", "quantity": 38, "unit": "EA", "status": "approved",
     "x": 402, "y": 300, "evidence": {"sheet": "E1.1", "detail": "Ceiling grid, open office", "crop": "device"}},
    {"id": "it-09", "sheet": "E1.1", "symbol": "run", "name": '1" EMT conduit run',
     "description": "Branch circuit home run from lighting panel to corridor fixtures.",
     "system": "Lighting", "category": "Conduit and wire", "quantity": 96, "unit": "LF", "status": "missing",
     "path": [[232, 232], [232, 372], [468, 372]],
     "warning": {
         "title": "Missing scale reference",
         "found": "No scale label was found in the E1.1 title block.",
         "why": "Without a scale, this run could not be measured and its length is an estimate only.",
         "fix": "Set the drawing scale for E1.1, or calibrate against a known dimension on the plan.",
         "where": "E1.1 title block",
     },
     "evidence": {"sheet": "E1.1", "detail": "Title block", "crop": "titleblock"}},
    {"id": "it-10", "sheet": "E1.1", "symbol": "switch", "name": "Single-pole wall switch",
     "description": "Toggle switch at office and conference room doors, +48\" AFF.",
     "system": "Lighting", "category": "Devices", "quantity": 11, "unit": "EA", "status": "ready",
     "x": 596, "y": 254, "evidence": {"sheet": "E1.1", "detail": "Typical switch tag", "crop": "device"}},
    {"id": "it-11", "sheet": "E1.1", "symbol": "junction", "name": '4" square junction box',
     "description": "Concealed above ceiling, lighting circuit splice point.",
     "system": "Lighting", "category": "Boxes", "quantity": 9, "unit": "EA", "status": "ready",
     "x": 300, "y": 466, "evidence": {"sheet": "E1.1", "detail": "Ceiling plan detail 3", "crop": "device"}},
    {"id": "it-12", "sheet": "E1.1", "symbol": "data", "name": "Data outlet, 2-port",
     "description": "Cat 6 outlet at workstations, ring and string by electrical contractor.",
     "system": "Low voltage", "category": "Devices", "quantity": 22, "unit": "EA", "status": "ready",
     "x": 700, "y": 430, "evidence": {"sheet": "E1.1", "detail": "Workstation typical", "crop": "device"}},
]


def run(db: DbSession, email: str, password: str) -> Project:
    """Creates the demo org, one user, and the prototype's seed takeoff
    ("Meridian Distribution Center," ported from src/lib/data.js).

    Idempotent: returns the existing project immediately if `PROJECT_ID`
    is already present, writing nothing. See the module docstring for
    what makes that safe -- deterministic ids plus every row landing in
    one caller-controlled transaction, never partially.
    """
    if not email or not password:
        raise ValueError("seed.run() requires a non-empty email and password -- there is no default credential.")

    existing = db.get(Project, PROJECT_ID)
    if existing is not None:
        return existing

    org = db.get(Org, ORG_ID)
    if org is None:
        org = Org(id=ORG_ID, name="Meridian Electric")
        db.add(org)

    normalized_email = email.lower().strip()
    user_id = _seed_uuid(f"user:{normalized_email}")
    user = db.get(User, user_id)
    if user is None:
        # Named "Dana Whitfield" regardless of the credential's email --
        # that is the identity data.js's two pre-approved items
        # (`approvedBy: "Dana Whitfield"`) actually refer to. The
        # credential supplied through the environment is how *this*
        # deployment signs in as that identity; it is not a display name.
        user = User(id=user_id, org_id=org.id, email=normalized_email,
                    password_hash=hash_password(password), name="Dana Whitfield", color="#23528f")
        db.add(user)
    db.flush()

    project = Project(
        id=PROJECT_ID,
        org_id=org.id,
        name="Meridian Distribution Center",
        number="26-0207",
        customer="Bellweather Construction",
        location="Stockton, CA",
        # Relative to today rather than a fixed literal, so the seed stays
        # honest about how far out the bid is however long after seeding
        # it's opened -- a hardcoded date silently becomes a project that
        # was due last year.
        bid_due_date=date.today() + timedelta(days=21),
        stage="review",
        revision_set_label="E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1",
    )
    db.add(project)
    db.flush()

    sheet_ids: dict[str, uuid.UUID] = {}
    for order, row in enumerate(SHEETS_DATA):
        sheet_id = _seed_uuid(f"sheet:{row['id']}")
        sheet_ids[row["id"]] = sheet_id
        db.add(Sheet(
            id=sheet_id, project_id=project.id, number=row["number"], title=row["title"],
            discipline=row["discipline"], revision=row["revision"],
            revision_date=date.fromisoformat(row["revision_date"]), scale=row["scale"],
            scale_options=row["scale_options"], plan=row["plan"], sort_order=order,
        ))
    db.flush()

    for row in ITEMS_DATA:
        item = Item(
            id=_seed_uuid(f"item:{row['id']}"), project_id=project.id, sheet_id=sheet_ids[row["sheet"]],
            symbol=row["symbol"], name=row["name"], description=row["description"], system=row["system"],
            category=row["category"], quantity=row["quantity"], unit=row["unit"],
            status=STATUS_BY_KEY[row["status"]], x=row.get("x"), y=row.get("y"), path=row.get("path"),
            notes="", evidence=row.get("evidence"),
        )
        if row["status"] == "approved":
            item.approved_by_user_id = user.id
            item.approved_at = _APPROVED_AT
        db.add(item)
        db.flush()

        warning = row.get("warning")
        if warning is not None:
            db.add(Warning(
                id=_seed_uuid(f"warning:{row['id']}"), item_id=item.id,
                reason=WARNING_REASON_BY_TITLE[warning["title"]], title=warning["title"],
                found=warning["found"], why=warning["why"], fix=warning["fix"], where_=warning["where"],
            ))

    db.flush()
    return project


def _seed_env_credentials() -> tuple[str, str]:
    """Read SEED_EMAIL / SEED_PASSWORD from the environment, exiting
    loudly (never falling back to a baked-in credential) if either is
    unset or blank.
    """
    email = os.environ.get("SEED_EMAIL", "").strip()
    password = os.environ.get("SEED_PASSWORD", "")
    missing = [name for name, value in (("SEED_EMAIL", email), ("SEED_PASSWORD", password)) if not value]
    if missing:
        raise SystemExit(
            f"{' and '.join(missing)} must be set in the environment. There is no default seed "
            "password -- set both before running `python -m app.seed`."
        )
    return email, password


def main() -> None:
    email, password = _seed_env_credentials()
    db = SessionLocal()
    try:
        project = run(db, email, password)
        db.commit()
        print(f"Seeded {project.name} ({project.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
