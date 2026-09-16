"""The engine split along the job boundaries: three entry points that
take a path and typed records and return typed records, and the old
whole-document estimate rebuilt on top of them so there is one code path."""
import pymupdf
import pytest

from app.engine import classification, documents, estimate, sheet as sheet_mod
from app.engine.contracts import Classification, DeviceCluster, Placement
from tests.bid_set import first_vector_set  # existing helper naming a corpus PDF, skips if absent


def _blank_pdf(tmp_path, pages=1, encrypt=False):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=612, height=792)
    p = tmp_path / "t.pdf"
    if encrypt:
        doc.save(p, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    else:
        doc.save(p)
    return str(p)


def test_read_reports_page_count_and_no_sheets_for_a_blank_page(tmp_path):
    reading = documents.read(_blank_pdf(tmp_path, pages=2), "Drawings")
    assert reading.page_count == 2
    assert reading.sheets == []          # zero paths + zero images is not a sheet
    assert reading.context_text == ""
    assert reading.scope == []


def test_read_raises_a_typed_error_for_an_encrypted_file(tmp_path):
    with pytest.raises(documents.EncryptedDocument):
        documents.read(_blank_pdf(tmp_path, encrypt=True), "Drawings")


def test_read_raises_a_typed_error_for_garbage(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4\nnot really")
    with pytest.raises(documents.UnreadableDocument):
        documents.read(str(p), "Drawings")


def test_read_of_a_specification_returns_context_not_sheets(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "DIVISION 26 ELECTRICAL\nSECTION 26 05 19 WIRE AND CABLE\nCIRCUIT breakers by others")
    p = tmp_path / "spec.pdf"; doc.save(p)
    reading = documents.read(str(p), "Specifications")
    assert reading.sheets == []
    assert "DIVISION 26" in reading.context_text


def test_classify_run_without_a_key_is_deterministic(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sheets = [documents.sheet_from_row(0, "E2.1", "Power plan", "1/8\"=1'", 2000, 1500, [0, 0, 2000, 1500], "plan", "", [], "")]
    clusters = [DeviceCluster(tag="R", sheet_page_index=0, placements=[Placement(100, 100), Placement(200, 200)])]
    cls = classification.classify_run(clusters, sheets, "", "", [], "Charlotte, NC")
    assert cls.source == "deterministic"
    assert cls.labor_rate > 0 and cls.material_factor > 0
    assert "R" in cls.catalog_items


def test_finish_prices_a_sheets_clusters_and_crops_evidence(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    path = first_vector_set()
    reading = documents.read(path, "Drawings")
    plan = next(s for s in reading.sheets if s.kind == "plan" and not s.unreadable_reason)
    from app.engine import counting
    clusters = counting.count_sheet(path, plan)
    assert clusters, "the corpus set's first plan should count something"
    cls = classification.classify_run(clusters, reading.sheets, "", "", [], "")
    result = sheet_mod.finish(path, plan, clusters, cls, reading.sheets)
    assert len(result.rows) == len(clusters)
    row = result.rows[0]
    assert row["sheet_id"] == str(plan.page_index) and row["page"] == plan.page_index + 1
    assert row["total_cost"] == round(row["material_cost"] + row["labor_cost"], 2)
    assert row["evidence_png_b64"]            # a crop was rendered
    assert result.ai_reading is None          # no key, no vision


def test_full_takeoff_still_produces_the_same_shape(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    payload = estimate.full_takeoff(first_vector_set(), "")
    assert {"sheets", "items", "totals", "source", "labor_rate", "material_factor"} <= set(payload)
    assert all({"id", "number", "page", "width_pt", "height_pt", "kind"} <= set(s) for s in payload["sheets"])
