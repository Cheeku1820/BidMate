"""match: every copy of one drawn box on one sheet (B3b spec §6). By
shape when the box holds a vector glyph, by render otherwise. Writes the
result onto the symbol_matches row; creates no item -- a person names
the result first (app/matches)."""
from __future__ import annotations

import uuid

import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine import documents, glyphs, legend_symbols, raster_match
from app.engine.contracts import DetectedSheet
from app.engine.page_frame import visual_words
from app.takeoff.ingest import denormalize_box, normalize_point, SHEET_SPACE_H, SHEET_SPACE_W
from app.takeoff.models import Document, Job, Sheet, SymbolMatch
from app.worker.blobs import blob_to_tempfile
from app.worker.classify_job import _detected
from app.worker.handlers import register


def _rect_close(a, b, tol: float = 0.01) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def find_matches(path: str, page_index: int, sheet: DetectedSheet, rect,
                  glyph_info: dict | None = None) -> list[tuple[float, float, float, float]]:
    """Page-point rects of every copy of what is inside `rect`, the boxed
    one included -- even when it sits outside the sheet's counting
    region. `glyphs_on(page, sheet.region, words)` only looks inside that
    region (the title-block strip is carved out of it), but the box the
    estimator drew is not bound by it: a real glyph in the strip is
    still the thing they boxed, so it is prepended when the region-bound
    search does not already carry it. One function, two methods: the
    glyph in the box decides. The page's paths are parsed once and
    handed to both lookups: parsing is most of the job's time on a dense
    sheet (Pulte E-210: two parses ran ≈59 s against the 60 s match
    timeout), and the box and the region read the same paths.

    `glyph_info`, when given a dict, is filled in with the open `page`
    and the boxed glyph's own tight rect (`None` on the raster path --
    no vector glyph to point at). B3c: a caller that also wants to
    silhouette the boxed glyph (`legend_symbols.silhouette`) reads it
    from here rather than opening and re-parsing the page a second
    time -- this parse is most of the job's time, see above."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    words = visual_words(page)
    paths = glyphs.paths_on(page)
    glyph = glyphs.glyph_in(page, rect, words, paths=paths)
    if glyph is not None:
        matches = [g.rect for g in glyphs.matches_of(glyph, glyphs.glyphs_on(page, sheet.region, words, paths=paths))]
        if not any(_rect_close(glyph.rect, r) for r in matches):
            matches = [glyph.rect] + matches
        if glyph_info is not None:
            glyph_info["page"], glyph_info["glyph_rect"] = page, glyph.rect
        return matches
    if glyph_info is not None:
        glyph_info["page"], glyph_info["glyph_rect"] = page, None
    return raster_match.find_on_render(path, page_index, rect)


def _to_sheet_units(rects, width_pt: float, height_pt: float) -> list[list[int]]:
    out = []
    for x0, y0, x1, y1 in rects:
        out.append([normalize_point((x0 + x1) / 2, width_pt, SHEET_SPACE_W), normalize_point((y0 + y1) / 2, height_pt, SHEET_SPACE_H),
                    max(1, normalize_point(x1 - x0, width_pt, SHEET_SPACE_W)), max(1, normalize_point(y1 - y0, height_pt, SHEET_SPACE_H))])
    return out


def _project_templates(db: Session, project_id) -> list:
    """Every legend row on the project (B3c spec §3), read from every
    sheet's own stored `symbol_templates` in one query -- never one
    query per sheet, and never a re-render of a legend's silhouettes
    (those are already on the row, from the read job)."""
    rows = db.scalars(select(Sheet.symbol_templates).where(Sheet.project_id == project_id))
    return [documents.template_from_row(t) for row in rows for t in (row or [])]


@register("match")
def run(db: Session, job: Job) -> None:
    match = db.get(SymbolMatch, job.symbol_match_id) if job.symbol_match_id else None
    sheet = db.get(Sheet, match.sheet_id) if match is not None else None
    doc = db.get(Document, uuid.UUID(sheet.takeoff_id)) if sheet is not None and sheet.takeoff_id else None
    if match is None or sheet is None or doc is None:
        return   # deleted between queue and run
    detected = _detected(sheet)
    rect = denormalize_box(match.box, sheet.width_pt, sheet.height_pt)
    with blob_to_tempfile(doc.storage_key, doc.filename) as path:
        glyph_info: dict = {}
        rects = find_matches(path, detected.page_index, detected, rect, glyph_info=glyph_info)
        # B3c: a drawn box carries no subscript, so the modifier is "" --
        # only legend rows with no modifier of their own are eligible.
        silhouette = legend_symbols.silhouette(glyph_info["page"], glyph_info["glyph_rect"] or rect)
    match.matches = _to_sheet_units(rects, sheet.width_pt, sheet.height_pt)
    match.status, match.error = "found", ""
    ranked = legend_symbols.rank_templates(silhouette, "", _project_templates(db, match.project_id))
    match.suggested_name = legend_symbols.sentence_case(ranked[0].description) if ranked else ""
    db.flush()
