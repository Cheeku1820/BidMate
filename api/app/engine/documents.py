"""Documents agent (v1).

Reads the source PDF and emits DetectedSheet records for the electrical
sheets: which pages are electrical, each sheet's number/scale from the
title block, the drawing region device tags are counted within (excluding
the title-block strip), and the schedule/legend text the Classification
agent reads. It is language over a deterministic shell -- geometry and
text extraction, no localization guessing.

Scanned sheets are marked unreadable with a reason rather than returned as
a thin list of items (CLAUDE.md: silence reads as completeness). v1 reads
vector sheets only; a raster page is flagged, never silently counted.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pymupdf

from .contracts import DetectedSheet
from .legend import parse_legend

# A sheet number like E2.1 / E0.2 / E10.1.
SHEET_ID = re.compile(r"\bE\d{1,2}\.\d{1,2}\b")
# A drafting scale like 1/8" = 1'-0"  (very forgiving).
SCALE = re.compile(r'\d{1,2}/\d{1,2}"?\s*=\s*\d')

# The title block is a vertical strip on the right of a landscape E-size
# sheet. Counting the drawing area excludes it (and a thin border) so a
# tag in the title block or a schedule cell is never counted as a device.
RIGHT_STRIP = 0.82
BORDER = 0.03

# A crop around one item's counted location(s), for the item panel's
# evidence view. A point item gets a fixed radius around its single
# coordinate; a multi-placement cluster gets the bounding box of every
# placement plus a margin, so the crop shows the group Counting actually
# found rather than one instance of it -- see render_evidence_crop.
EVIDENCE_POINT_RADIUS_PT = 90
EVIDENCE_CLUSTER_MARGIN_PT = 40
EVIDENCE_MAX_PX = 640      # longest output edge, in pixels
EVIDENCE_MIN_ZOOM = 0.5
EVIDENCE_MAX_ZOOM = 4.0

SCHEDULE_KEYWORDS = ("SCHEDULE", "LUMINAIRE", "FIXTURE", "LEGEND", "MANUFACTURER")


def _is_raster(page: pymupdf.Page) -> bool:
    area = page.rect.width * page.rect.height or 1
    cover = 0.0
    for im in page.get_image_info():
        b = im.get("bbox")
        if b:
            r = pymupdf.Rect(b)
            cover = max(cover, (r.width * r.height) / area)
    return cover > 0.6 and len(page.get_drawings()) < 50


def _sheet_number(page: pymupdf.Page, text: str) -> str:
    """The sheet's own number, read from its title block first.

    The title block is the one place on the page an E-number is
    guaranteed to name *this* sheet rather than a sheet it references —
    a detail callout bubble ("see 2/E5.1") can otherwise repeat a
    different sheet's number more often than the title block states this
    one's, and the most-frequent heuristic below would pick the wrong
    sheet. RIGHT_STRIP is the same boundary `detect_sheets` already uses
    to exclude the title block from device counting, reused here rather
    than duplicated so the two never drift apart.
    """
    w, h = page.rect.width, page.rect.height
    tb_text = page.get_text("text", clip=pymupdf.Rect(w * RIGHT_STRIP, 0, w, h))
    ids = SHEET_ID.findall(tb_text)
    if not ids:
        # Some sets have no machine-readable text in a consistent
        # title-block box -- fall back to the whole page rather than
        # returning nothing.
        ids = SHEET_ID.findall(text)
    if not ids:
        return ""
    return max(set(ids), key=ids.count)


def _scale(text: str) -> str:
    m = SCALE.search(text)
    return m.group(0) if m else ""


def detect_sheets(path: str) -> list[DetectedSheet]:
    doc = pymupdf.open(path)
    sheets: list[DetectedSheet] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        text = page.get_text("text")
        # Electrical sheet: carries an E-series number and is a drawing.
        if not SHEET_ID.search(text):
            continue
        w, h = page.rect.width, page.rect.height
        region = (w * BORDER, h * BORDER, w * RIGHT_STRIP, h * (1 - BORDER))
        if _is_raster(page):
            sheets.append(
                DetectedSheet(
                    page_index=pno, number=_sheet_number(page, text), title="Electrical",
                    discipline="Electrical", scale="", width_pt=w, height_pt=h, region=region,
                    unreadable_reason="Scanned sheet — vector reading isn't available yet, so it was not counted.",
                )
            )
            continue
        # Only count drawing sheets (plans), not text-only pages.
        if len(page.get_drawings()) < 500:
            continue
        sched = text if any(k in text.upper() for k in SCHEDULE_KEYWORDS) else ""
        sheets.append(
            DetectedSheet(
                page_index=pno, number=_sheet_number(page, text), title="Electrical plan",
                discipline="Electrical", scale=_scale(text), width_pt=w, height_pt=h,
                region=region, schedule_text=sched,
                # parse_legend reads text and cannot know which page it came
                # from; the caller does, so it stamps each row here.
                legend=[replace(e, page_index=pno) for e in parse_legend(sched)],
            )
        )
    return sheets


_CONTEXT_KEYWORDS = (
    "LUMINAIRE", "FIXTURE", "SCHEDULE", "PANEL", "RECEPTACLE", "LIGHTING",
    "DIVISION 26", "26 05", "26 24", "26 27", "26 51", "WATT", "CIRCUIT", "DISCONNECT",
)


def extract_context(pdf_bytes: bytes, max_chars: int = 6000) -> str:
    """Pull the electrical-relevant text out of a spec/addendum PDF so the
    classifier can read a fixture or panel schedule that lives outside the
    drawings. Only pages that mention Division 26 topics are included, and
    the total is capped -- untrusted document text is context for the
    model, never an instruction, and it stays bounded."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    chunks: list[str] = []
    total = 0
    for page in doc:
        text = page.get_text("text")
        if any(k in text.upper() for k in _CONTEXT_KEYWORDS):
            chunks.append(text.strip())
            total += len(text)
            if total > max_chars:
                break
    return "\n".join(chunks)[:max_chars]


def first_pages_text(pdf_bytes: bytes, pages: int = 2, max_chars: int = 4000) -> str:
    """The text of a document's first pages -- enough to read a cover
    sheet, a spec section header, or a drawing title block."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for i in range(min(pages, doc.page_count)):
        out.append(doc[i].get_text("text"))
    return "\n".join(out)[:max_chars]


def classify_content(text: str) -> str | None:
    """Guess a document's type from its first-page text, for files whose
    name didn't say. Returns None when nothing is conclusive, so the
    caller keeps the filename guess rather than overriding it with a
    weak signal. Checked in the same priority order as the filename
    rules (an addendum first)."""
    up = (text or "").upper()
    if "ADDENDUM" in up or "ADDENDA" in up:
        return "Addendum"
    if "SPECIFICATION" in up or "DIVISION 26" in up or re.search(r"\bSECTION 26 ?\d", up) or "PROJECT MANUAL" in up:
        return "Specifications"
    if "SCOPE OF WORK" in up:
        return "Scope"
    if "GEOTECHNICAL" in up or "BID TABULATION" in up:
        return "Other"
    # Drawing indicators: an electrical sheet number in a title block, or a
    # scale label alongside a sheet reference.
    if re.search(r"\bE\d{1,2}\.\d{1,2}\b", up) or ("SCALE:" in up and "SHEET" in up):
        return "Drawings"
    return None


def render_vision_png_bytes(pdf_bytes: bytes, page_index: int, long_edge_px: int = 1500) -> bytes:
    """Render a sheet sized for a vision model to read -- the long edge
    around 1500px, which is where Claude reads a drawing well without the
    cost of a full-resolution image."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    zoom = long_edge_px / max(page.rect.width, page.rect.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")



def render_evidence_crop(
    path: str,
    page_index: int,
    page_width_pt: float,
    page_height_pt: float,
    placements: list[tuple[float, float]],
) -> bytes | None:
    """A tight PNG crop of the source page around one item's counted
    location(s), for the item panel's evidence view.

    Zoom is chosen so the crop's longest edge lands near
    EVIDENCE_MAX_PX regardless of how large the bounding box is -- a
    cluster spread across most of a sheet renders at a lower zoom
    rather than having placements cropped out of frame; nothing here
    ever discards a placement to keep zoom high.

    Returns None on any failure -- a missing crop must never fail the
    takeoff, the same principle the vision pass in estimate_service.py
    already follows.
    """
    if not placements or page_width_pt <= 0 or page_height_pt <= 0:
        return None
    try:
        xs = [p[0] for p in placements]
        ys = [p[1] for p in placements]
        if len(placements) == 1:
            x, y = xs[0], ys[0]
            x0 = x - EVIDENCE_POINT_RADIUS_PT
            y0 = y - EVIDENCE_POINT_RADIUS_PT
            x1 = x + EVIDENCE_POINT_RADIUS_PT
            y1 = y + EVIDENCE_POINT_RADIUS_PT
        else:
            x0 = min(xs) - EVIDENCE_CLUSTER_MARGIN_PT
            y0 = min(ys) - EVIDENCE_CLUSTER_MARGIN_PT
            x1 = max(xs) + EVIDENCE_CLUSTER_MARGIN_PT
            y1 = max(ys) + EVIDENCE_CLUSTER_MARGIN_PT

        x0 = max(0.0, x0)
        y0 = max(0.0, y0)
        x1 = min(float(page_width_pt), x1)
        y1 = min(float(page_height_pt), y1)
        if x1 <= x0 or y1 <= y0:
            return None

        bbox_w, bbox_h = x1 - x0, y1 - y0
        zoom = EVIDENCE_MAX_PX / max(bbox_w, bbox_h)
        zoom = max(EVIDENCE_MIN_ZOOM, min(EVIDENCE_MAX_ZOOM, zoom))

        doc = pymupdf.open(path)
        page = doc[page_index]
        clip = pymupdf.Rect(x0, y0, x1, y1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        return pix.tobytes("png")
    except Exception:  # noqa: BLE001 -- a missing crop must never fail the takeoff
        return None
