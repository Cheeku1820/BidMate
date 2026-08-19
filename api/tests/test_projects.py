"""app/takeoff/models.py's Project -- the dashboard fields spec §5.1's
projects table renders. task-1-brief.md.
"""

import datetime

from app.takeoff.models import Project


def test_project_carries_dashboard_fields(db, org):
    """The dashboard columns in spec §5.1 need somewhere to live. A project
    with no bid date and no assigned estimator is valid -- both are optional
    at creation (spec §6.1) -- so the columns are nullable rather than
    defaulted to a fake date."""
    project = Project(
        org_id=org.id,
        name="Riverside Medical Center - Bldg C",
        number="26-0418",
        customer="Hensel Phelps",
        location="Sacramento, CA",
        bid_due_date=datetime.date(2026, 9, 14),
        estimator_user_id=None,
        stage="review",
    )
    db.add(project)
    db.flush()

    assert project.number == "26-0418"
    assert project.customer == "Hensel Phelps"
    assert project.location == "Sacramento, CA"
    assert project.bid_due_date == datetime.date(2026, 9, 14)
    assert project.estimator_user_id is None
    assert project.stage == "review"
    assert project.archived_at is None
    assert project.updated_at is not None


def test_project_defaults_are_empty_not_null(db, org):
    """A project created from the minimal form (name and address only) must
    still render every dashboard column without the table printing 'None'.
    Empty string beats NULL for the text columns for exactly that reason."""
    project = Project(org_id=org.id, name="Untitled bid")
    db.add(project)
    db.flush()

    assert project.number == ""
    assert project.customer == ""
    assert project.location == ""
    assert project.stage == "setup"
    assert project.bid_due_date is None
