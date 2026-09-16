"""Documents agent (v1).

Reads the source PDF and emits DetectedSheet records for the electrical
sheets: which pages are electrical, each sheet's number, title and kind
from the title block, the drawing region device tags are counted within
(the visual page less the located title-block strip), and the
schedule/legend text the Classification agent reads. It is language over a deterministic shell -- geometry and
text extraction, no localization guessing.

Scanned sheets are marked unreadable with a reason rather than returned as
a thin list of items (CLAUDE.md: silence reads as completeness). v1 reads
vector sheets only; a raster page is flagged, never silently counted.
"""

from __future__ import annotations

import re
from dataclasses import replace

import pymupdf

from . import scope, sheet_kind, title_block
from .contracts import DetectedSheet, DocumentReading, LegendEntry
from .legend import parse_legend
from .page_frame import visual_words

# A drafting scale like 1/8" = 1'-0"  (very forgiving).
SCALE = re.compile(r'\d{1,2}/\d{1,2}"?\s*=\s*\d')

# The thin border taken off every edge of the counting region. The
# title-block strip itself is located per page (title_block.locate), not
# assumed to sit on the right -- see _region.
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

# Estimator-facing, in a drafter's words: what the page is and what that
# means for the takeoff, no file internals (CLAUDE.md). Each is one
# sentence ending in a period; the canvas banner strips the period and
# continues with what to do about it.
SCANNED_REASON = "The sheet is a scanned image with no readable text, so it was not counted."
OUTLINED_REASON = "The sheet's text was saved as outlines rather than text, so its tags could not be read and it was not counted."

# A page with no words at all but this many drawing paths is a sheet
# whose text was outlined to paths when the PDF was made (TSC
# Nutrition's fourteen electrical pages: 3,000-14,000 paths, zero
# words). Below it, a wordless page is a border rule and a logo box --
# nothing. Pages with images and no words are scans (_is_raster).
OUTLINED_MIN_DRAWINGS = 200


# A page is a scan when it is pixels and next to nothing else: under
# RASTER_MAX_DRAWINGS vector paths, and either its images cover more than
# RASTER_COVER of the page or it carries no text at all. Coverage is
# summed over every image -- FedEx and Gerber split each scan into two
# bands, neither covering more than half the page, and the largest band
# alone said "not a scan" for every one of their pages.
RASTER_MAX_DRAWINGS = 50
RASTER_COVER = 0.6


def _has_drawings(page: pymupdf.Page) -> bool:
    """Whether the page draws anything at all. get_cdrawings() is the
    thin C-level walk without the per-path Python dicts get_drawings()
    builds; asked only for emptiness, it is the cheap question. A
    165k-path architectural page was walked in full twice per pass --
    once here, once in _is_raster -- to learn it was not empty."""
    return bool(page.get_cdrawings())


def _is_raster(page: pymupdf.Page) -> bool:
    # Images and text first: both are cheap. get_drawings() is walked
    # last, only for a page that already looks like a scan -- it runs on
    # every page without a number, and a 165k-path architectural page
    # takes seconds to walk.
    box = pymupdf.Rect(page.mediabox)  # image bboxes are in the unrotated frame
    area = box.width * box.height or 1
    cover = 0.0
    for im in page.get_image_info():
        b = im.get("bbox")
        if b:
            r = pymupdf.Rect(b) & box
            cover += (r.width * r.height) / area
    if cover <= 0:
        return False
    if cover <= RASTER_COVER and page.get_text("text").strip():
        return False
    return len(page.get_drawings()) < RASTER_MAX_DRAWINGS


def _unreadable(page: pymupdf.Page, words: list) -> tuple[str, str] | None:
    """Why a page with no readable title block is still a sheet nobody
    can read: (title, reason), or None when the page is simply not a
    sheet. One path, two reasons -- a scan and a page of outlined text
    are the same outcome for the estimator, a page of the set that was
    not counted and says so. _is_raster decides which."""
    if _is_raster(page):
        return "Scanned sheet", SCANNED_REASON
    if not words and (page.get_image_info() or len(page.get_drawings()) >= OUTLINED_MIN_DRAWINGS):
        # Any image, or enough paths. A wordless page with an image and
        # too many paths to be a scan is still a page nobody can read;
        # it must not fall between the two conditions and vanish.
        return "Sheet with outlined text", OUTLINED_REASON
    return None


def _scale(text: str) -> str:
    m = SCALE.search(text)
    return m.group(0) if m else ""


class EncryptedDocument(Exception):
    """The file needs a password to open."""


class UnreadableDocument(Exception):
    """Not a PDF the parser can read, or zero pages."""


def _open_checked(path: str) -> pymupdf.Document:
    """Open a PDF or raise one of the two typed errors above. `read` and
    `detect_sheets` both go through here so they agree on what an
    unreadable file is."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # noqa: BLE001 -- pymupdf raises several types for bad bytes
        raise UnreadableDocument(type(exc).__name__) from exc
    if doc.is_encrypted and doc.needs_pass:
        raise EncryptedDocument()
    if doc.page_count == 0:
        raise UnreadableDocument("zero pages")
    return doc


SCOPE_MAX_CHARS = 12000


def _drawing_scope_pages(path: str, sheets: list[DetectedSheet]) -> list[tuple[int, str]]:
    """The non-plan sheets' text, for scope statements that live in a
    drawing set's general notes rather than a spec: legend, schedule and
    diagram sheets carry these, plans don't. `schedule_text` already
    holds a schedule/legend sheet's text (documents.detect_sheets); a
    sheet without one (a general-notes sheet, or one whose text didn't
    match SCHEDULE_KEYWORDS) is read fresh here -- one extra open of the
    file, acceptable for how rarely scope language sits outside a plan's
    title block. Capped like extract_context: untrusted document text is
    context for the model, never an instruction, and stays bounded."""
    candidates = [s for s in sheets if s.kind != "plan"]
    if not candidates:
        return []
    reopened: pymupdf.Document | None = None
    pages: list[tuple[int, str]] = []
    total = 0
    try:
        for s in candidates:
            if total >= SCOPE_MAX_CHARS:
                break
            text = s.schedule_text
            if not text:
                if reopened is None:
                    reopened = pymupdf.open(path)
                text = reopened[s.page_index].get_text("text")
            if not text:
                continue
            text = text[: SCOPE_MAX_CHARS - total]
            pages.append((s.page_index, text))
            total += len(text)
    finally:
        if reopened is not None:
            reopened.close()
    return pages


def read(path: str, doc_type: str) -> DocumentReading:
    """One file, read once. Drawings yield sheets; every other type
    yields context text. Either way, `scope.extract` runs over the same
    Division 26-relevant pages the rest of the Documents agent already
    selected -- a spec's context_pages, or a drawing set's non-plan
    sheets -- so scope statements are quoted from material the agent was
    already reading, not a fresh pass over the file."""
    doc = _open_checked(path)
    page_count = doc.page_count
    doc.close()
    if doc_type == "Drawings":
        sheets = detect_sheets(path)
        pages = _drawing_scope_pages(path, sheets)
        return DocumentReading(sheets=sheets, page_count=page_count, context_text="", scope=scope.extract(pages))
    with open(path, "rb") as fh:
        pages = context_pages(fh.read(), max_chars=SCOPE_MAX_CHARS)
    text = "\n".join(t for _, t in pages)[:SCOPE_MAX_CHARS]
    return DocumentReading(sheets=[], page_count=page_count, context_text=text, scope=scope.extract(pages))


def sheet_to_payload(s: DetectedSheet) -> dict:
    """The dict `estimate.full_takeoff` emits per sheet."""
    return {
        "id": str(s.page_index),
        "number": s.number,
        "page": s.page_index + 1,
        "width_pt": s.width_pt,
        "height_pt": s.height_pt,
        "unreadable": s.unreadable_reason or None,
        "title": s.title,
        "scale": s.scale,
        "kind": s.kind,
    }


def sheet_from_row(page_index, number, title, scale, width_pt, height_pt, region, kind,
                   schedule_text, legend, unreadable_reason) -> DetectedSheet:
    """Rebuild the Documents agent's record from what the read job stored,
    so classify and sheet jobs never re-open the file to get it."""
    entries = [LegendEntry(**e) for e in (legend or [])]
    return DetectedSheet(
        page_index=page_index, number=number or "", title=title or "", discipline="Electrical",
        scale=scale or "", width_pt=float(width_pt), height_pt=float(height_pt),
        region=tuple(region) if region else (0.0, 0.0, float(width_pt), float(height_pt)),
        kind=kind or "plan", schedule_text=schedule_text or "", legend=entries,
        unreadable_reason=unreadable_reason or "",
    )


def detect_sheets(path: str) -> list[DetectedSheet]:
    doc = _open_checked(path)
    sheets: list[DetectedSheet] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        w, h = page.rect.width, page.rect.height  # visual frame
        text = page.get_text("text")
        words = visual_words(page)

        # An electrical sheet is a page whose own title-block number cell
        # holds a family token. No whole-page fallback: architectural
        # pages say "SEE E-101" and would otherwise be pulled in.
        tb = title_block.locate(words, w, h)
        number = title_block.sheet_number(tb) if tb else ""
        if not number:
            # A scanned page, or one whose text is outlined to paths, has
            # no text to find a title block in. It is still a page of the
            # set, so it is emitted as a sheet nobody can read rather
            # than dropped: silence reads as completeness.
            unreadable = _unreadable(page, words)
            if unreadable:
                title, reason = unreadable
                sheets.append(
                    DetectedSheet(
                        page_index=pno, number="", title=title,
                        discipline="Electrical", scale="", width_pt=w, height_pt=h,
                        region=_border(w, h), kind="other", unreadable_reason=reason,
                    )
                )
            continue

        # A sheet is a drawing. A page with no drawing paths and no
        # images -- a project-manual page whose left column happens to
        # say SHEET / E7.1 / DATE -- cannot be a plan, a schedule or a
        # legend drawing. Zero, not a count: Pulte Sagebriar's 323-path
        # riser diagram is a sheet.
        if not page.get_image_info() and not _has_drawings(page):
            continue

        region = _region(w, h, tb.strip)
        if _is_raster(page):
            # A scan whose title block happened to be text -- a stamp
            # over the image, a number cell typed in after scanning. The
            # number is real; nothing else on the page has been read, so
            # it is the same outcome as an unnumbered scan: "Scanned
            # sheet", kind other, and no title taken from a block that
            # was not read. It used to say "Electrical" / plan here,
            # which claimed a reading nobody made.
            sheets.append(
                DetectedSheet(
                    page_index=pno, number=number, title="Scanned sheet",
                    discipline="Electrical", scale="", width_pt=w, height_pt=h, region=region,
                    kind="other", unreadable_reason=SCANNED_REASON,
                )
            )
            continue
        scale = _scale(text)
        raw_title = title_block.title(tb, number)
        kind = sheet_kind.classify(raw_title, text, bool(scale))
        sched = text if any(k in text.upper() for k in SCHEDULE_KEYWORDS) else ""
        sheets.append(
            DetectedSheet(
                page_index=pno, number=number, title=raw_title or sheet_kind.label(kind),
                discipline="Electrical", scale=scale, width_pt=w, height_pt=h,
                region=region, kind=kind, schedule_text=sched,
                # parse_legend reads text and cannot know which page it came
                # from; the caller does, so it stamps each row here.
                legend=[replace(e, page_index=pno) for e in parse_legend(sched)],
            )
        )
    return sheets


def _border(w: float, h: float) -> tuple[float, float, float, float]:
    """The visual page minus the border, for a page with no title block."""
    return (w * BORDER, h * BORDER, w * (1 - BORDER), h * (1 - BORDER))


def _region(w: float, h: float, strip: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """The visual page minus a border minus the located title-block
    strip. Replaces the old fixed right strip, which was built in the
    rotated frame and applied to unrotated text (spec 1.1)."""
    x0, y0, x1, y1 = _border(w, h)
    sx0, sy0, sx1, sy1 = strip
    if sx0 > 0 and sx1 >= w:      # right strip
        x1 = min(x1, sx0)
    elif sx1 < w:                 # left strip
        x0 = max(x0, sx1)
    elif sy0 > 0:                 # bottom strip
        y1 = min(y1, sy0)
    else:                         # top strip
        y0 = max(y0, sy1)
    return (x0, y0, x1, y1)


_CONTEXT_KEYWORDS = (
    "LUMINAIRE", "FIXTURE", "SCHEDULE", "PANEL", "RECEPTACLE", "LIGHTING",
    "DIVISION 26", "26 05", "26 24", "26 27", "26 51", "WATT", "CIRCUIT", "DISCONNECT",
)


def context_pages(pdf_bytes: bytes, max_chars: int = 6000) -> list[tuple[int, str]]:
    """The Division 26-relevant pages of a spec/addendum PDF, as
    (page_index, text) pairs -- what the classifier reads for a fixture or
    panel schedule that lives outside the drawings, and what scope.extract
    reads for a scope letter or spec section. Only pages that mention
    Division 26 topics are included, and the total is capped -- untrusted
    document text is context for the model, never an instruction, and it
    stays bounded."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages: list[tuple[int, str]] = []
    total = 0
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if any(k in text.upper() for k in _CONTEXT_KEYWORDS):
            # Accumulate on the unstripped length -- the cap `extract_context`
            # always used -- even though the stored chunk is stripped; the
            # two must agree byte-for-byte with the pre-split behaviour, or
            # the page selected right at the boundary can change.
            pages.append((i, text.strip()))
            total += len(text)
            if total > max_chars:
                break
    return pages


def extract_context(pdf_bytes: bytes, max_chars: int = 6000) -> str:
    """Pull the electrical-relevant text out of a spec/addendum PDF so the
    classifier can read a fixture or panel schedule that lives outside the
    drawings. A thin join over context_pages, so the two selections can
    never drift apart."""
    pages = context_pages(pdf_bytes, max_chars=max_chars)
    return "\n".join(t for _, t in pages)[:max_chars]


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
    # scale label alongside a sheet reference. The whole family
    # (title_block.SHEET_ID): a set numbered E-101 or EL101 is a drawing
    # set as surely as one numbered E2.1. This is a document-type guess
    # over the first pages, not the page-level "is this an electrical
    # sheet" decision, which never applies the family to whole-page text.
    if title_block.SHEET_ID.search(up) or ("SCALE:" in up and "SHEET" in up):
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

    `placements` and the page dimensions are in the visual frame, which
    is the frame `get_pixmap(clip=...)` takes -- no transform here
    (page_frame.py).

    Zoom is chosen so the crop's longest edge lands near
    EVIDENCE_MAX_PX regardless of how large the bounding box is -- a
    cluster spread across most of a sheet renders at a lower zoom
    rather than having placements cropped out of frame; nothing here
    ever discards a placement to keep zoom high.

    Returns None on any failure -- a missing crop must never fail the
    takeoff, the same principle the vision pass in sheet.finish follows.
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
