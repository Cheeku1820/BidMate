"""The real thing: the Unalaska set's first plan renders, and every counted
placement falls inside the paper after the draw-time rescale."""
from app.engine import counting, documents, tiles
from tests.bid_set import first_vector_set


def test_first_plan_renders_and_placements_fall_inside_the_paper(tmp_path):
    path = first_vector_set()
    reading = documents.read(path, "Drawings")
    plan = next(s for s in reading.sheets if s.kind == "plan" and not s.unreadable_reason)
    ts = tiles.render_sheet(path, plan.page_index, str(tmp_path))
    assert ts.width_pt == plan.width_pt and ts.height_pt == plan.height_pt
    assert 72 * ts.levels[-1].scale >= tiles.TARGET_DPI
    clusters = counting.count_sheet(path, plan)
    paper_h = round(1000 * plan.height_pt / plan.width_pt)
    for c in clusters:
        for p in c.placements:
            x = p.x / plan.width_pt * 1000
            y = (p.y / plan.height_pt * 750) * (paper_h / 750)
            assert 0 <= x <= 1000 and 0 <= y <= paper_h
