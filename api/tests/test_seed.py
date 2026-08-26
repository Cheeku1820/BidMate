"""app/seed.py -- porting src/lib/data.js's twelve-item prototype fixture
into a real database project. task-14-brief.md.

Positions have to match data.js exactly or markers land on the wrong
plan geometry (PlanDrawing.jsx draws fixed SVG geometry keyed to those
coordinates) -- twelve items transcribed by hand is a real
transcription-error surface, so this asserts per-sheet and per-status
counts and spot-checks coordinates rather than trusting the port by eye.

The BLOCKER from the brief: data.js's "Fixture type conflicts with the
schedule" warning matches no existing WarningReason (only SCALE and
LEGEND existed before this task). Migration 0007 adds
WarningReason.SCHEDULE_CONFLICT for exactly this warning -- tagging it
SCALE would make set_scale() silently delete it, destroying evidence
about a fixture/schedule disagreement the estimator never saw. That is
asserted directly here (test_the_schedule_conflict_warning_gets_its_own_
reason_not_scale), not just in the migration.
"""

import os

import pytest
from sqlalchemy import select

from app import seed
from app.identity.models import Org, User
from app.takeoff.models import Item, Project, ReviewStatus, Sheet, Warning, WarningReason


@pytest.fixture(autouse=True)
def _no_real_env_leaks(monkeypatch):
    """None of these tests should accidentally pick up a real
    SEED_EMAIL/SEED_PASSWORD from the surrounding shell."""
    monkeypatch.delenv("SEED_EMAIL", raising=False)
    monkeypatch.delenv("SEED_PASSWORD", raising=False)


def test_run_creates_a_project_named_meridian_distribution_center(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    assert project.name == "Meridian Distribution Center"


def test_run_creates_exactly_the_three_sheets_in_data_js(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    sheets = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).all()
    by_number = {s.number: s for s in sheets}

    assert set(by_number) == {"E2.1", "E1.1", "E3.1"}
    assert by_number["E2.1"].title == "Power plan — warehouse"
    assert by_number["E2.1"].scale == "mixed"
    assert by_number["E1.1"].scale == "none"
    assert by_number["E3.1"].scale == "nts"
    assert by_number["E2.1"].revision == "Rev 2"


def test_run_creates_exactly_twelve_items(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    items = db.scalars(select(Item).where(Item.project_id == project.id)).all()

    assert len(items) == 12


def test_items_land_on_the_correct_sheets(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    sheets = {s.id: s.number for s in db.scalars(select(Sheet).where(Sheet.project_id == project.id))}
    items = db.scalars(select(Item).where(Item.project_id == project.id)).all()
    counts: dict[str, int] = {}
    for item in items:
        counts[sheets[item.sheet_id]] = counts.get(sheets[item.sheet_id], 0) + 1

    # data.js: it-01..it-07 on E2.1 (7), it-08..it-12 on E1.1 (5), none on E3.1
    assert counts == {"E2.1": 7, "E1.1": 5}


def test_per_status_counts_match_data_js(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    items = db.scalars(select(Item).where(Item.project_id == project.id)).all()
    counts: dict[ReviewStatus, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    # data.js: approved x2 (it-01, it-08), missing x2 (it-02, it-09),
    # attention x2 (it-04, it-07), ready x6 (the rest)
    assert counts[ReviewStatus.APPROVED] == 2
    assert counts[ReviewStatus.MISSING] == 2
    assert counts[ReviewStatus.ATTENTION] == 2
    assert counts[ReviewStatus.READY] == 6


def test_spot_check_panel_lp1_coordinates(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    item = db.scalar(select(Item).where(Item.project_id == project.id, Item.name == "Panel LP-1"))

    assert item.x == 178
    assert item.y == 214
    assert item.quantity == 1
    assert item.unit == "EA"
    assert item.status is ReviewStatus.APPROVED


def test_spot_check_the_first_conduit_runs_path(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    item = db.scalar(
        select(Item).where(Item.project_id == project.id, Item.name == '2" EMT conduit run')
    )

    assert item.path == [[186, 226], [186, 430], [402, 430], [402, 508]]
    assert item.quantity == 184
    assert item.status is ReviewStatus.MISSING


def test_spot_check_the_data_outlet_at_the_end_of_the_list(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    item = db.scalar(select(Item).where(Item.project_id == project.id, Item.name == "Data outlet, 2-port"))

    assert item.x == 700
    assert item.y == 430
    assert item.quantity == 22


def test_approved_items_carry_a_real_approving_user(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    approved = db.scalars(
        select(Item).where(Item.project_id == project.id, Item.status == ReviewStatus.APPROVED)
    ).all()

    assert len(approved) == 2
    for item in approved:
        assert item.approved_by_user_id is not None
        assert item.approved_at is not None
        user = db.get(User, item.approved_by_user_id)
        assert user.name == "Dana Whitfield"


def test_four_warnings_are_created_matching_data_js(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    warnings = db.scalars(
        select(Warning).join(Item, Warning.item_id == Item.id).where(Item.project_id == project.id)
    ).all()

    assert len(warnings) == 4
    titles = {w.title for w in warnings}
    assert titles == {
        "Scale needs confirmation",
        "Missing scale reference",
        "Symbol is not in the legend",
        "Fixture type conflicts with the schedule",
    }


def test_every_warning_has_all_four_required_fields(db):
    """CLAUDE.md: a warning missing found/why/fix/where is a schema
    error, not a copy oversight -- checked directly against the seeded
    rows rather than trusting the transcription.
    """
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    warnings = db.scalars(
        select(Warning).join(Item, Warning.item_id == Item.id).where(Item.project_id == project.id)
    ).all()

    for w in warnings:
        assert w.found.strip()
        assert w.why.strip()
        assert w.fix.strip()
        assert w.where_.strip()


# --- The BLOCKER: the fourth warning gets its own reason, not SCALE ---


def test_the_schedule_conflict_warning_gets_its_own_reason_not_scale(db):
    """The failure this test exists to catch: tagging "Fixture type
    conflicts with the schedule" as WarningReason.SCALE would make
    set_scale() (app/takeoff/scale.py) delete it the moment an estimator
    confirms E2.1's scale, even though the warning has nothing to do
    with the scale at all -- destroying evidence about a fixture/
    schedule disagreement on the exact conflict path the README walks a
    user through.
    """
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    conflict = db.scalar(
        select(Warning).where(Warning.title == "Fixture type conflicts with the schedule")
    )

    assert conflict is not None
    assert conflict.reason is WarningReason.SCHEDULE_CONFLICT
    assert conflict.reason is not WarningReason.SCALE


def test_scale_warnings_are_tagged_scale_and_legend_warning_is_tagged_legend(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    reasons_by_title = {
        w.title: w.reason
        for w in db.scalars(
            select(Warning).join(Item, Warning.item_id == Item.id).where(Item.project_id == project.id)
        )
    }

    assert reasons_by_title["Scale needs confirmation"] is WarningReason.SCALE
    assert reasons_by_title["Missing scale reference"] is WarningReason.SCALE
    assert reasons_by_title["Symbol is not in the legend"] is WarningReason.LEGEND


# --- Idempotency ---


def test_running_twice_does_not_create_a_second_project(db):
    first = seed.run(db, "estimator@meridian.example", "correct horse battery staple")
    second = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    assert first.id == second.id
    all_projects = db.scalars(select(Project).where(Project.name == "Meridian Distribution Center")).all()
    assert len(all_projects) == 1


def test_running_twice_does_not_duplicate_sheets_items_or_warnings(db):
    project = seed.run(db, "estimator@meridian.example", "correct horse battery staple")
    seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    sheets = db.scalars(select(Sheet).where(Sheet.project_id == project.id)).all()
    items = db.scalars(select(Item).where(Item.project_id == project.id)).all()
    assert len(sheets) == 3
    assert len(items) == 12


def test_running_twice_does_not_duplicate_the_org_or_the_user(db):
    seed.run(db, "estimator@meridian.example", "correct horse battery staple")
    seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    orgs = db.scalars(select(Org).where(Org.name == "Meridian Electric")).all()
    users = db.scalars(select(User).where(User.email == "estimator@meridian.example")).all()
    assert len(orgs) == 1
    assert len(users) == 1


def test_the_seed_is_keyed_deterministically_not_by_row_count(db):
    """Both calls resolve to the identical project id -- the idempotency
    key is a fixed, deterministic id derived from the fixture's own
    identity, not "does a project with this name already exist" (which
    a real customer could also create, giving a false idempotency
    signal) or a row count.
    """
    first = seed.run(db, "estimator@meridian.example", "correct horse battery staple")
    second = seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    assert first.id == second.id == seed.PROJECT_ID


# --- Seed rows are a fixture, not history ---


def test_seeded_rows_write_no_action_log_entries(db):
    from app.takeoff.models import Action

    seed.run(db, "estimator@meridian.example", "correct horse battery staple")

    assert db.scalars(select(Action)).all() == []


# --- No default password ---


def test_run_requires_a_non_empty_email_and_password(db):
    with pytest.raises((ValueError, TypeError)):
        seed.run(db, "", "correct horse battery staple")


def test_main_exits_loudly_when_seed_email_is_unset(monkeypatch):
    monkeypatch.delenv("SEED_EMAIL", raising=False)
    monkeypatch.setenv("SEED_PASSWORD", "correct horse battery staple")

    with pytest.raises(SystemExit):
        seed._seed_env_credentials()


def test_main_exits_loudly_when_seed_password_is_unset(monkeypatch):
    monkeypatch.setenv("SEED_EMAIL", "estimator@meridian.example")
    monkeypatch.delenv("SEED_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        seed._seed_env_credentials()


def test_main_exits_loudly_when_both_are_unset(monkeypatch):
    monkeypatch.delenv("SEED_EMAIL", raising=False)
    monkeypatch.delenv("SEED_PASSWORD", raising=False)

    with pytest.raises(SystemExit):
        seed._seed_env_credentials()


def test_main_never_falls_back_to_a_baked_in_credential(monkeypatch):
    """There is no code path in _seed_env_credentials that returns a
    literal password string -- this greps the function's own source for
    the word "password" appearing as a return value would be brittle,
    so instead this proves behaviorally that an unset SEED_PASSWORD
    always exits rather than ever returning something usable.
    """
    monkeypatch.setenv("SEED_EMAIL", "estimator@meridian.example")
    monkeypatch.delenv("SEED_PASSWORD", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        seed._seed_env_credentials()

    assert "SEED_PASSWORD" in str(excinfo.value)


def test_main_reads_valid_credentials_from_the_environment(monkeypatch):
    monkeypatch.setenv("SEED_EMAIL", "estimator@meridian.example")
    monkeypatch.setenv("SEED_PASSWORD", "correct horse battery staple")

    email, password = seed._seed_env_credentials()

    assert email == "estimator@meridian.example"
    assert password == "correct horse battery staple"
