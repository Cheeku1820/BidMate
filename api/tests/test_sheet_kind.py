from app.engine import sheet_kind


def test_kinds_are_the_closed_set():
    assert sheet_kind.KINDS == ("plan", "schedule", "legend", "diagram", "other")


def test_title_decides_first():
    assert sheet_kind.classify("Panel schedules", "", True) == "schedule"
    assert sheet_kind.classify("Electrical legend and abbreviations", "", False) == "legend"
    assert sheet_kind.classify("One-line diagram", "", False) == "diagram"
    assert sheet_kind.classify("Lighting controls", "", False) == "diagram"
    assert sheet_kind.classify("First floor power plan", "", True) == "plan"
    assert sheet_kind.classify("Cover sheet", "", False) == "other"


def test_content_markers_when_the_title_is_silent():
    sched = "PANEL SCHEDULE ... LUMINAIRE SCHEDULE ... VA CKT AMP"
    assert sheet_kind.classify("", sched, False) == "schedule"
    assert sheet_kind.classify("", "ON / OFF " * 5, False) == "diagram"
    assert sheet_kind.classify("", "READING AREA  STACKS/ADULT", True) == "plan"


def test_one_schedule_header_is_not_enough():
    """A plan sheet with one embedded lighting schedule block is still a plan."""
    assert sheet_kind.classify("", "LUMINAIRE SCHEDULE  A  B  C", True) == "plan"


def test_a_scale_outranks_content_markers():
    assert sheet_kind.classify("", "PANEL SCHEDULE  LUMINAIRE SCHEDULE", True) == "plan"


def test_unsure_is_plan():
    assert sheet_kind.classify("", "", False) == "plan"


def test_labels_are_sentence_case():
    assert [sheet_kind.label(k) for k in sheet_kind.KINDS] == [
        "Electrical plan", "Schedule", "Legend", "Diagram", "Sheet",
    ]
