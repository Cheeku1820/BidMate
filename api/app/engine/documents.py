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

import pymupdf

from .contracts import DetectedSheet

# A sheet number like E2.1 / E0.2 / E10.1.
SHEET_ID = re.compile(r"\bE\d{1,2}\.\d{1,2}\b")
# A drafting scale like 1/8" = 1'-0"  (very forgiving).
SCALE = re.compile(r'\d{1,2}/\d{1,2}"?\s*=\s*\d')

# The title block is a vertical strip on the right of a landscape E-size
# sheet. Counting the drawing area excludes it (and a thin border) so a
# tag in the title block or a schedule cell is never counted as a device.
RIGHT_STRIP = 0.82
BORDER = 0.03

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


def _sheet_number(text: str) -> str:
    ids = SHEET_ID.findall(text)
    if not ids:
        return ""
    # The sheet's own number is the one that repeats most in its own text
    # (title block + references back to itself); good enough for v1, and
    # the estimator can correct it.
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
                    page_index=pno, number=_sheet_number(text), title="Electrical",
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
                page_index=pno, number=_sheet_number(text), title="Electrical plan",
                discipline="Electrical", scale=_scale(text), width_pt=w, height_pt=h,
                region=region, schedule_text=sched,
            )
        )
    return sheets


def render_page_png(path: str, page_index: int, zoom: float = 2.0) -> bytes:
    """Render a sheet to PNG for the canvas to show behind the markers.
    A real blueprint needs its own page image; the drawn SVG is only for
    the seed fixture."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")


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


def render_vision_png_bytes(pdf_bytes: bytes, page_index: int, long_edge_px: int = 1500) -> bytes:
    """Render a sheet sized for a vision model to read -- the long edge
    around 1500px, which is where Claude reads a drawing well without the
    cost of a full-resolution image."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    zoom = long_edge_px / max(page.rect.width, page.rect.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")


def render_page_png_bytes(pdf_bytes: bytes, page_index: int, zoom: float = 1.6) -> bytes:
    """Same, from the PDF bytes the service keeps in memory keyed by
    takeoff id (so the canvas can fetch one sheet image on demand without
    the whole set living in the browser)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")
