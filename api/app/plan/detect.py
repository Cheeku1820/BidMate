"""What the plan derives from what the read job stored -- pure functions
over plain values, no database and no file. docs/specs/
project-plan-screen.md, "Derivation".

Keys are what a decision is stored against, so they name the thing
found (a section number, a sheet, a phase label) rather than where in
the text it sat: the same section quoted from a different line next
read keeps its decision. Nothing on a Line or Question says how it was
found."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.plan import copy

CONTEXT_DOC_TYPES = ("Specifications", "Addendum", "Scope", "Other")

# A Division 26/27/28 section number at the start of a line, in any of
# the forms a project manual uses: "26 05 19", "260519", "26-05-19",
# with or without a leading SECTION, and an optional level-4 MasterFormat
# suffix ("26 05 33.13", or the compact "26 0533.13"). The title is the
# rest of the line, or the next non-empty line when the number stands
# alone.
_SECTION = re.compile(
    r"^\s*(?:SECTION\s+)?(26|27|28)[\s\-]?(\d\d)[\s\-]?(\d\d)(?:\.(\d\d))?\b[\s\-–—:.]*(.*)$",
    re.IGNORECASE,
)

# The schedule headings sheet_kind looks for when it classifies a sheet.
# Spelled here rather than imported: app.plan stays out of app.engine.
SCHEDULE_HEADINGS = ("PANEL SCHEDULE", "LUMINAIRE SCHEDULE", "FIXTURE SCHEDULE", "EQUIPMENT SCHEDULE", "MECHANICAL SCHEDULE")

# "PHASE 1", "Phase A", "PHASE II". The number or letter is required, so
# "the next phase of the work" is not a phase.
_PHASE = re.compile(r"\bPHASE\s+(\d{1,2}|[A-Z]|I{1,3}|IV|V)\b", re.IGNORECASE)

# A table-of-contents dot leader run, or an unleadered page-number column
# (two-plus spaces then a digit, e.g. "GROUNDING AND BONDING   26 05 26-1").
# Whichever comes first in the title marks where the real title ends.
_TOC_TRAILER = re.compile(r"\.{3,}|\ {2,}\d")


def _cut_toc_trailer(title: str) -> str:
    m = _TOC_TRAILER.search(title)
    if m:
        title = title[:m.start()]
    return title.rstrip(" .:-")


@dataclass(frozen=True)
class DocIn:
    id: str
    filename: str
    doc_type: str
    status: str
    context_text: str
    page_count: int | None


@dataclass(frozen=True)
class SheetIn:
    id: str
    document_id: str
    number: str
    title: str
    kind: str
    page_index: int
    scale: str
    scale_options: tuple
    unreadable_reason: str
    schedule_text: str


@dataclass(frozen=True)
class Place:
    document_id: str
    document_filename: str
    page: int | None
    quote: str


@dataclass
class Line:
    key: str
    kind: str
    text: str
    place: Place
    division: str | None = None
    sheet_number: str | None = None
    places: list[Place] = field(default_factory=list)


@dataclass
class Question:
    key: str
    rule: str
    title: str
    found: str
    why: str
    fix: str
    where: str
    document_id: str | None


def _readable(s: SheetIn) -> bool:
    return not s.unreadable_reason


def _filenames(docs: list[DocIn]) -> dict[str, str]:
    return {d.id: d.filename for d in docs}


def spec_sections(docs: list[DocIn]) -> list[Line]:
    out: list[Line] = []
    for d in docs:
        if d.doc_type not in CONTEXT_DOC_TYPES or d.status != "processed" or not d.context_text:
            continue
        seen: set[str] = set()
        lines = d.context_text.splitlines()
        for i, raw in enumerate(lines):
            m = _SECTION.match(raw)
            if not m:
                continue
            division, a, b, suffix, title = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5).strip()
            quote = raw.strip()
            if not title:
                nxt = next((l.strip() for l in lines[i + 1:i + 3] if l.strip()), "")
                if not nxt or _SECTION.match(nxt):
                    continue
                title = nxt
                # The quote is evidence: both verbatim lines, leaders and all.
                quote = f"{quote} {nxt}"
            title = _cut_toc_trailer(title)
            if not title:
                continue
            number = f"{division}{a}{b}{suffix or ''}"
            if number in seen:
                continue
            seen.add(number)
            dotted = f"{division} {a} {b}.{suffix}" if suffix else f"{division} {a} {b}"
            out.append(Line(
                key=f"spec:{d.id}:{number}", kind="spec_section",
                text=f"{dotted} — {title}",
                place=Place(d.id, d.filename, None, quote[:600]), division=division,
            ))
    return out


def _heading_label(heading: str) -> str:
    return heading[0] + heading[1:].lower()


def schedules(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]:
    names = _filenames(docs)
    out: list[Line] = []
    for s in sheets:
        if not _readable(s):
            continue
        fn = names.get(s.document_id, "")
        page = s.page_index + 1
        if s.kind in ("schedule", "legend"):
            out.append(Line(key=f"schedule:sheet:{s.id}", kind="schedule", text=s.title,
                            place=Place(s.document_id, fn, page, s.title), sheet_number=s.number))
            continue
        upper = s.schedule_text.upper()
        for heading in SCHEDULE_HEADINGS:
            if heading in upper:
                quote = next((l.strip() for l in s.schedule_text.splitlines() if heading in l.upper()), heading)
                out.append(Line(key=f"schedule:heading:{s.id}:{heading}", kind="schedule",
                                text=f"{_heading_label(heading)} on {s.number}",
                                place=Place(s.document_id, fn, page, quote[:600]), sheet_number=s.number))
    return out


def normalise_phase(label: str) -> str:
    token = re.sub(r"(?i)^\s*PHASE\s+", "", label.strip()).strip()
    return "PHASE " + token.upper()


def phase_display(norm: str) -> str:
    return "Phase " + norm[len("PHASE "):]


def phases(sheets: list[SheetIn], docs: list[DocIn]) -> list[Line]:
    names = _filenames(docs)
    found: dict[str, list[Place]] = {}

    def add(label: str, place: Place) -> None:
        found.setdefault(normalise_phase(label), []).append(place)

    for s in sheets:
        if not _readable(s):
            continue
        fn = names.get(s.document_id, "")
        page = s.page_index + 1
        for m in _PHASE.finditer(s.title):
            add(m.group(1), Place(s.document_id, fn, page, s.title))
        for raw in s.schedule_text.splitlines():
            for m in _PHASE.finditer(raw):
                add(m.group(1), Place(s.document_id, fn, page, raw.strip()[:600]))
    for d in docs:
        if d.doc_type not in CONTEXT_DOC_TYPES or d.status != "processed":
            continue
        for raw in d.context_text.splitlines():
            for m in _PHASE.finditer(raw):
                add(m.group(1), Place(d.id, d.filename, None, raw.strip()[:600]))

    out = []
    for norm in found:
        places = []
        for p in found[norm]:
            if p not in places:
                places.append(p)
        out.append(Line(key=f"phase:{norm}", kind="phase", text=phase_display(norm), place=places[0], places=places))
    return out


def questions(sheets: list[SheetIn], docs: list[DocIn], *, scope_count: int, phase_count: int, schedule_count: int) -> list[Question]:
    out: list[Question] = []
    processed = [d for d in docs if d.status == "processed"]
    drawings = [d for d in processed if d.doc_type == "Drawings"]

    for d in drawings:
        pages = [s for s in sheets if s.document_id == d.id]
        unreadable = [s for s in pages if not _readable(s)]
        if unreadable:
            total = len(pages) if pages else (d.page_count or 0)
            out.append(Question(key=f"question:scanned:{d.id}", rule="scanned", document_id=d.id,
                                **copy.scanned(d.filename, len(unreadable), total)))

    if drawings and not any(d.doc_type == "Specifications" for d in processed):
        out.append(Question(key="question:no_specs:project", rule="no_specs", document_id=None, **copy.no_specs()))
    if processed and scope_count == 0:
        out.append(Question(key="question:no_scope:project", rule="no_scope", document_id=None, **copy.no_scope()))

    for s in sheets:
        if s.kind == "plan" and _readable(s) and not s.scale and not s.scale_options:
            out.append(Question(key=f"question:no_scale:{s.id}", rule="no_scale", document_id=s.document_id,
                                **copy.no_scale(s.number, s.title)))

    readable_plans = any(s.kind == "plan" and _readable(s) for s in sheets)
    if readable_plans and phase_count == 0:
        out.append(Question(key="question:no_phasing:project", rule="no_phasing", document_id=None, **copy.no_phasing()))
    if readable_plans and schedule_count == 0:
        out.append(Question(key="question:no_schedule:project", rule="no_schedule", document_id=None, **copy.no_schedule()))
    return out
