from app.takeoff import scale as scale_module
from app.takeoff.models import Item, ReviewStatus, Warning


def _blocked(db, project, sheet):
    i = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
             system="Power", category="Conduit and wire", quantity=184, unit="LF",
             status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]])
    db.add(i)
    db.flush()
    db.add(Warning(item_id=i.id, title="Missing scale reference", found="No scale label was found.",
                   why="This run could not be measured.", fix="Set the drawing scale.", where_="E1.1 title block"))
    db.flush()
    return i


def test_setting_the_scale_releases_every_blocked_item_on_that_sheet(db, dana, project, sheet):
    one, two = _blocked(db, project, sheet), _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert sheet.scale == '1/8" = 1\'-0"'
    assert one.status is ReviewStatus.READY
    assert two.status is ReviewStatus.READY


def test_the_warnings_on_released_items_are_cleared(db, dana, project, sheet):
    item = _blocked(db, project, sheet)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert db.query(Warning).filter(Warning.item_id == item.id).count() == 0


def test_it_is_one_action_naming_how_many_items_moved(db, dana, project, sheet):
    _blocked(db, project, sheet)
    _blocked(db, project, sheet)

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.kind == "scale"
    assert "2 measured items" in action.label
    assert len(action.before["items"]) == 2


def test_items_on_another_sheet_are_untouched(db, dana, project, sheet):
    from app.takeoff.models import Sheet

    other = Sheet(project_id=project.id, number="E1.1", title="Lighting plan", discipline="Electrical",
                  revision="Rev 3", scale="none", scale_options=[], plan="office")
    db.add(other)
    db.flush()
    elsewhere = _blocked(db, project, other)

    scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert elsewhere.status is ReviewStatus.MISSING


def test_the_recorded_action_carries_enough_to_reverse_both_halves(db, dana, project, sheet):
    """Task 10 has to restore the sheet's previous scale AND every
    released item's previous status AND the warning that explained it --
    so the compound action's `before` must carry the sheet's old scale,
    each item's id and prior status, and each item's warning fields, not
    just item ids and statuses.
    """
    item = _blocked(db, project, sheet)

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.before["scale"] == "mixed"
    assert action.after["scale"] == '1/8" = 1\'-0"'

    before_item = action.before["items"][0]
    assert before_item["id"] == str(item.id)
    assert before_item["status"] == "missing"
    assert len(before_item["warnings"]) == 1
    assert before_item["warnings"][0]["title"] == "Missing scale reference"
    assert before_item["warnings"][0]["found"] == "No scale label was found."
    assert before_item["warnings"][0]["why"] == "This run could not be measured."
    assert before_item["warnings"][0]["fix"] == "Set the drawing scale."
    assert before_item["warnings"][0]["where_"] == "E1.1 title block"


def test_an_item_with_no_warning_is_still_recorded_with_an_empty_warnings_list(db, dana, project, sheet):
    item = Item(project_id=project.id, sheet_id=sheet.id, symbol="run", name='2" EMT conduit run',
                system="Power", category="Conduit and wire", quantity=184, unit="LF",
                status=ReviewStatus.MISSING, path=[[186, 226], [186, 430]])
    db.add(item)
    db.flush()

    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.before["items"][0]["warnings"] == []


def test_setting_the_scale_on_a_sheet_with_no_blocked_items_still_records_one_action(db, dana, project, sheet):
    action = scale_module.set_scale(db, dana, sheet, '1/8" = 1\'-0"')
    db.flush()

    assert action.kind == "scale"
    assert sheet.scale == '1/8" = 1\'-0"'
    assert action.before["items"] == []
    assert "0 measured items" in action.label
