from app.takeoff import symbol_library
from app.takeoff.models import SymbolResolution


def test_overlay_names_a_resolved_tag_at_ready_with_no_warning(db, org, project, dana):
    db.add(SymbolResolution(org_id=org.id, project_id=project.id, tag="F", name="2x4 LED troffer, 4000K — type F",
                            system="Lighting", category="Fixtures", catalog_id=None, resolved_by_user_id=dana.id))
    db.flush()
    rows = [
        {"source_tag": "F", "name": "Luminaire type F", "system": "Lighting", "category": "Fixtures", "status": "attention",
         "warning": {"title": "t", "found": "f", "why": "w", "fix": "x", "where": "E-501", "reason": "classification"}, "description": ""},
        {"source_tag": "R", "name": "20A duplex receptacle", "system": "Power", "category": "Devices", "status": "ready",
         "warning": None, "description": ""},
    ]
    changed = symbol_library.overlay(db, project.id, rows)
    assert changed == 1
    assert rows[0]["name"] == "2x4 LED troffer, 4000K — type F" and rows[0]["status"] == "ready" and rows[0]["warning"] is None
    assert rows[0]["description"] == "Read as 2x4 LED troffer, 4000K — type F from your earlier review."
    assert rows[1]["name"] == "20A duplex receptacle"


def test_overlay_never_approves(db, org, project, dana):
    db.add(SymbolResolution(org_id=org.id, project_id=project.id, tag="F", name="x", system="Lighting",
                            category="Fixtures", catalog_id=None, resolved_by_user_id=dana.id))
    db.flush()
    rows = [{"source_tag": "F", "name": "Luminaire type F", "system": "Lighting", "category": "Fixtures", "status": "attention", "warning": None, "description": ""}]
    symbol_library.overlay(db, project.id, rows)
    assert rows[0]["status"] == "ready"
