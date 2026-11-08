"""Task 8 of docs/plans/rom-estimate.md -- the assembled document.

What this file is really asserting is that the ROM never borrows the
review workspace's vocabulary. There is no approval step on this
document, so none of the four review labels may appear in its shape or
its copy, and every line carries `counted` or `assumed` instead.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.estimate.write import regenerate
from app.takeoff.models import Assumption, Item, ReviewStatus, Sheet


def url(project):
    return f"/api/projects/{project.id}/estimate"


def _sheet(project, *, number="EL101", scale="1/8\" = 1'-0\"", **kw):
    return Sheet(project_id=project.id, number=number, title="Lighting plan",
                 discipline="Electrical", revision="Rev 2", scale=scale,
                 scale_options=[], plan="showroom", **kw)


def _item(project, sheet, *, name="20A duplex receptacle", system="Power",
          material="100", labor="40", status=ReviewStatus.READY, **kw):
    return Item(project_id=project.id, sheet_id=sheet.id, symbol="receptacle", name=name,
                system=system, category="Devices", quantity=Decimal("1"), unit="ea",
                status=status, x=100, y=100,
                material_cost=Decimal(material), labor_cost=Decimal(labor),
                labor_hours=Decimal("2"), total_cost=Decimal(material) + Decimal(labor), **kw)


@pytest.fixture
def priced_project(db, org, signed_in_user):
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="Kittle's Saxony", revision_set_label="E1.1 Rev 3",
                pricing_source="llm", pricing_note="Indiana regional basis")
    db.add(p)
    db.flush()
    s = _sheet(p)
    db.add(s)
    db.flush()
    db.add(_item(p, s))
    db.add(_item(p, s, name="2x4 LED troffer", system="Lighting", material="250", labor="60"))
    db.flush()
    # The worker writes these on every run (Task 9). The endpoint reads
    # rows rather than generating them -- that is what lets an
    # estimator's override survive being read back -- so a fixture that
    # skipped this would be testing a document with nothing assumed.
    regenerate(db, p)
    db.commit()
    return p


def find_line(body, needle):
    for section in body["sections"]:
        for line in section["lines"]:
            if needle.lower() in line["title"].lower():
                return line
    raise AssertionError(f"no line matching {needle!r} in {[l['title'] for s in body['sections'] for l in s['lines']]}")


# --- shape -------------------------------------------------------------


def test_endpoint_returns_four_sections_in_order(client, priced_project):
    body = client.get(url(priced_project)).json()
    assert [s["key"] for s in body["sections"]] == ["scope", "takeoff", "labor", "material"]


def test_every_line_carries_an_origin(client, priced_project):
    body = client.get(url(priced_project)).json()
    for section in body["sections"]:
        assert all(line["origin"] in ("counted", "assumed") for line in section["lines"])


def test_no_review_label_appears_anywhere_in_the_document(client, priced_project):
    """The ROM has no approval step, so the four labels that govern
    approval must not leak into it -- that is how a fifth status gets
    invented."""
    raw = client.get(url(priced_project)).text
    for label in ("Ready to review", "Needs attention", "Missing information", "Estimator approved"):
        assert label not in raw


def test_the_document_states_its_own_totals(client, priced_project):
    body = client.get(url(priced_project)).json()
    assert body["direct_cost"] == "450.00"
    assert body["counted_count"] == 2
    assert body["project_name"] == "Kittle's Saxony"
    assert body["sheet_count"] == 1


def test_every_assumed_line_carries_a_basis_and_a_where(client, priced_project):
    body = client.get(url(priced_project)).json()
    assumed = [l for s in body["sections"] for l in s["lines"] if l["origin"] == "assumed"]
    assert assumed
    for line in assumed:
        assert line["basis"]
        assert line["basis_label"]
        assert line["where"]


def test_counted_lines_carry_no_basis(client, priced_project):
    body = client.get(url(priced_project)).json()
    counted = [l for s in body["sections"] for l in s["lines"] if l["origin"] == "counted"]
    assert counted
    assert all(line["basis"] is None for line in counted)


def test_takeoff_counted_lines_are_grouped_by_system(client, priced_project):
    body = client.get(url(priced_project)).json()
    takeoff = next(s for s in body["sections"] if s["key"] == "takeoff")
    counted = [l["title"] for l in takeoff["lines"] if l["origin"] == "counted"]
    assert sorted(counted) == ["Lighting", "Power"]


def test_a_hundred_items_do_not_become_a_hundred_counted_rows(client, db, priced_project):
    s = db.query(Sheet).filter(Sheet.project_id == priced_project.id).first()
    for n in range(100):
        db.add(_item(priced_project, s, name=f"Receptacle {n}"))
    db.commit()
    body = client.get(url(priced_project)).json()
    takeoff = next(s for s in body["sections"] if s["key"] == "takeoff")
    counted = [l for l in takeoff["lines"] if l["origin"] == "counted"]
    assert len(counted) == 2
    assert body["counted_count"] == 102


# --- the range ---------------------------------------------------------


def test_the_range_brackets_the_number(client, priced_project):
    body = client.get(url(priced_project)).json()
    low, high = Decimal(body["range"]["low"]), Decimal(body["range"]["high"])
    assert low <= Decimal(body["direct_cost"]) <= high


def test_the_range_is_wider_than_a_point_when_anything_was_assumed(client, priced_project):
    body = client.get(url(priced_project)).json()
    assert Decimal(body["range"]["spread"]) > 0


# --- qualifications ----------------------------------------------------


def test_one_assumption_shared_by_forty_items_is_one_qualification(client, db, priced_project):
    """Review Focus 5 -- and the same guard against a re-run writing a
    duplicate."""
    for _ in range(2):
        db.add(Assumption(
            project_id=priced_project.id, section="takeoff", basis="inferred",
            subject_kind="project", title="Showroom ceiling height",
            found="No reflected ceiling plan in the set",
            why="Fixture drop lengths depend on it", where="EL101",
            value="14", unit="ft", source="engine",
        ))
    db.commit()
    titles = [q["title"] for q in client.get(url(priced_project)).json()["qualifications"]]
    assert len([t for t in titles if "ceiling" in t.lower()]) == 1


def test_qualifications_are_generated_from_the_assumed_lines(client, priced_project):
    body = client.get(url(priced_project)).json()
    assumed = {l["title"] for s in body["sections"] for l in s["lines"] if l["origin"] == "assumed"}
    for q in body["qualifications"]:
        assert q["title"] in assumed


def test_every_qualification_answers_the_four_questions(client, priced_project):
    for q in client.get(url(priced_project)).json()["qualifications"]:
        assert q["title"] and q["found"] and q["why"] and q["where"]
        assert q["basis_label"]


def test_scope_exclusions_lead_the_qualifications_block(client, priced_project):
    """An exclusion changes what the number covers rather than how
    precise it is, so a reader who stops after three lines should have
    read the ones that moved money."""
    quals = client.get(url(priced_project)).json()["qualifications"]
    exclusions = [i for i, q in enumerate(quals) if q["basis_label"] == "Standard exclusion"]
    others = [i for i, q in enumerate(quals) if q["basis_label"] != "Standard exclusion"]
    assert exclusions
    assert others
    assert max(exclusions) < min(others)


# --- exclusions --------------------------------------------------------


def test_an_exclusion_states_the_dollars_it_removed(client, db, priced_project):
    s = db.query(Sheet).filter(Sheet.project_id == priced_project.id).first()
    db.add(_item(priced_project, s, name="FA device", system="Fire alarm", material="500", labor="0"))
    db.add(Assumption(
        project_id=priced_project.id, section="scope", basis="standard_exclusion",
        subject_kind="system", subject_ref="Fire alarm", title="Fire alarm by others",
        found="Not addressed", why="It changes the number", where="Scope documents",
        source="engine",
    ))
    db.commit()
    body = client.get(url(priced_project)).json()
    assert body["excluded_value"] == "500.00"
    line = find_line(body, "Fire alarm by others")
    assert line["amount"] == "500.00"
    # And the money is out of the total.
    assert body["direct_cost"] == "450.00"


def test_an_exclusion_that_removed_nothing_states_no_dollars(client, db, priced_project):
    db.add(Assumption(
        project_id=priced_project.id, section="scope", basis="standard_exclusion",
        subject_kind="project", title="Temporary power excluded",
        found="Not addressed", why="It is commonly the GC's", where="Scope documents",
        source="engine",
    ))
    db.commit()
    body = client.get(url(priced_project)).json()
    assert body["excluded_value"] == "0"
    assert find_line(body, "Temporary power")["amount"] is None


# --- unpriced ----------------------------------------------------------


def test_an_unpriced_line_is_counted_and_reported(client, db, priced_project):
    s = db.query(Sheet).filter(Sheet.project_id == priced_project.id).first()
    db.add(_item(priced_project, s, name="Unclassified symbol", material="0", labor="0"))
    db.commit()
    assert client.get(url(priced_project)).json()["unpriced_count"] == 1


# --- empty -------------------------------------------------------------


def test_empty_project_renders_with_a_reason(client, db, org, signed_in_user):
    """Review Focus 1."""
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="Fresh job", revision_set_label="")
    db.add(p)
    db.commit()
    body = client.get(url(p)).json()
    assert body["direct_cost"] == "0"
    assert body["range"]["low"] == body["range"]["high"] == "0"
    assert body["empty_reason"]
    assert "nothing to estimate" in body["empty_reason"]


def test_a_set_nothing_could_read_says_so(client, db, org, signed_in_user):
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="Scanned job", revision_set_label="")
    db.add(p)
    db.flush()
    db.add(_sheet(p, unreadable_reason="The page is a scanned image with no readable text."))
    db.commit()
    assert "could be read" in client.get(url(p)).json()["empty_reason"]


def test_a_set_that_read_but_counted_nothing_says_so(client, db, org, signed_in_user):
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="Empty job", revision_set_label="")
    db.add(p)
    db.flush()
    db.add(_sheet(p))
    db.commit()
    assert "no Division 26 items" in client.get(url(p)).json()["empty_reason"]


def test_everything_excluded_is_not_a_bare_zero(client, db, org, signed_in_user):
    """Review Focus 3 -- $0 because scope removed it all is a different
    document from $0 because nothing was counted."""
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="All excluded", revision_set_label="")
    db.add(p)
    db.flush()
    s = _sheet(p)
    db.add(s)
    db.flush()
    db.add(_item(p, s, name="FA device", system="Fire alarm", material="500", labor="0"))
    db.add(Assumption(
        project_id=p.id, section="scope", basis="standard_exclusion",
        subject_kind="system", subject_ref="Fire alarm", title="Fire alarm by others",
        found="Not addressed", why="It changes the number", where="Scope documents",
        source="engine",
    ))
    db.commit()
    body = client.get(url(p)).json()
    assert body["direct_cost"] == "0"
    assert "excluded by the scope assumptions" in body["empty_reason"]
    assert body["excluded_value"] == "500.00"


def test_a_project_with_items_has_no_empty_reason(client, priced_project):
    assert client.get(url(priced_project)).json()["empty_reason"] is None


# --- superseded --------------------------------------------------------


def test_a_superseded_sheet_contributes_nothing(client, db, priced_project):
    dead = _sheet(priced_project, number="E1.0", superseded_at=datetime.now(timezone.utc))
    db.add(dead)
    db.flush()
    db.add(_item(priced_project, dead, name="On a dead sheet", material="9999"))
    db.commit()
    body = client.get(url(priced_project)).json()
    assert body["direct_cost"] == "450.00"
    assert body["sheet_count"] == 1


# --- tenancy -----------------------------------------------------------


def test_estimate_is_org_scoped(client, other_org_project):
    assert client.get(url(other_org_project)).status_code == 404


def test_estimate_requires_a_signed_in_user(client, db, org):
    from app.takeoff.models import Project

    p = Project(org_id=org.id, name="Private job", revision_set_label="")
    db.add(p)
    db.commit()
    assert client.get(url(p)).status_code == 401


def test_a_missing_project_is_the_same_404(client, signed_in_user):
    import uuid as _uuid

    class _Fake:
        id = _uuid.uuid4()

    assert client.get(url(_Fake())).status_code == 404
