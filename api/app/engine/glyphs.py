"""Glyphs on an exploded vector sheet (B3b spec §3).

Every vector set in the corpus is Tier B: symbols are exploded into
loose paths with no block definitions to read, so identity has to be
recovered from geometry. This module turns a page's small full-tone
paths into glyph candidates and decides when two candidates are the
same drawn symbol. It knows nothing about what a symbol is -- that is
Classification's job -- and every threshold here is a measured
constant with a test, never a learned weight (CLAUDE.md: Counting is
tested, not trained).

Everything is in the visual frame (page_frame.py).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

import pymupdf

from app.engine.page_frame import Word

# Ink: the architectural underlay is screened (grey); electrical work is
# full-tone. Luminance above this is background.
MAX_INK_LUMINANCE = 0.4
# Size: a path bigger than this on either side is a wall, a wire run, a
# border -- never part of a symbol; a candidate smaller than MIN on
# either side is a dash or a tick.
MAX_GLYPH_PT = 40.0
MIN_GLYPH_PT = 3.0
# Shape: a candidate with no curve, no closed path and no fill needs at
# least this many straight segments -- two dashes at a corner are a wall.
MIN_STRAIGHT_PATHS = 3
# Grouping: paths whose bboxes overlap or come within TOUCH_PT belong to
# one candidate; more than MAX_PATHS is hatch or a north arrow.
TOUCH_PT = 0.5
MAX_PATHS = 24
GRID_PT = 8.0
# Sameness: every point matches a point of its pair within TOL_PT.
# Exact hashing split identical receptacles over 0.02 pt of jitter.
TOL_PT = 0.35
# Signature: the exemplar's canonical form on this grid, for a stable id.
QUANT_PT = 0.25
# A cluster at the same coordinates on most plan sheets is a border or
# legend fixture (counting.count applies this).
FIXTURE_PT = 2.0


@dataclass
class Path:
    rect: tuple[float, float, float, float]
    pts: list[tuple[float, float]]
    fill: bool
    stroke: bool
    closed: bool
    curved: bool


Form = list[tuple[bool, bool, bool, list[tuple[float, float]]]]


@dataclass
class Glyph:
    rect: tuple[float, float, float, float]
    forms: list[Form]     # the eight dihedral forms; forms[0] is the identity
    key: tuple            # coarse bucket: (paths, point counts) -- extents are left
                           # to same_shape's point matching, which already tolerates
                           # TOL_PT; a rounded-size bucket edge would be tighter than
                           # that tolerance and split matching shapes apart


@dataclass
class ShapeCluster:
    signature: str
    members: list[Glyph]


def _luminance(rgb) -> float:
    r, g, b = (list(rgb) + [0, 0, 0])[:3]
    return 0.299 * r + 0.587 * g + 0.114 * b


def paths_on(page) -> list[Path]:
    """Every full-tone drawing path, points in the visual frame, bbox from
    the points (PyMuPDF's `rect` for a vertical line is empty and unions
    to nothing)."""
    m = page.rotation_matrix
    out: list[Path] = []
    for d in page.get_drawings():
        ink = d.get("color") or d.get("fill")
        if ink is None or _luminance(ink) > MAX_INK_LUMINANCE:
            continue
        pts: list[pymupdf.Point] = []
        curved = closed = False
        for it in d["items"]:
            if it[0] == "l":
                pts += [it[1], it[2]]
            elif it[0] == "c":
                pts += [it[1], it[2], it[3], it[4]]
                curved = True
            elif it[0] == "re":
                r = it[1]
                pts += [r.tl, r.tr, r.br, r.bl]
                closed = True
            elif it[0] == "qu":
                q = it[1]
                pts += [q.ul, q.ur, q.lr, q.ll]
                closed = True
        if not pts:
            continue
        vis = [pymupdf.Point(p) * m for p in pts]
        xs = [p.x for p in vis]
        ys = [p.y for p in vis]
        out.append(Path(rect=(min(xs), min(ys), max(xs), max(ys)), pts=[(p.x, p.y) for p in vis],
                        fill=bool(d.get("fill")), stroke=bool(d.get("color")),
                        closed=closed or bool(d.get("closePath")), curved=curved))
    return out


def _small(p: Path) -> bool:
    x0, y0, x1, y1 = p.rect
    return (x1 - x0) <= MAX_GLYPH_PT and (y1 - y0) <= MAX_GLYPH_PT


def _bbox(paths: list[Path]) -> tuple[float, float, float, float]:
    return (min(p.rect[0] for p in paths), min(p.rect[1] for p in paths),
            max(p.rect[2] for p in paths), max(p.rect[3] for p in paths))


def _touching(a, b) -> bool:
    return (b[0] <= a[2] + TOUCH_PT and b[2] >= a[0] - TOUCH_PT
            and b[1] <= a[3] + TOUCH_PT and b[3] >= a[1] - TOUCH_PT)


def _candidates(paths: list[Path]) -> list[list[Path]]:
    """Union-find over small paths, bucketed on a GRID_PT grid so a sheet
    of thirty thousand fragments stays linear."""
    n = len(paths)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, p in enumerate(paths):
        x0, y0, x1, y1 = p.rect
        # Pad by TOUCH_PT so a pair within touching distance across a grid
        # boundary still shares a cell (paths right at the line would
        # otherwise never be compared and a symbol straddling it would
        # split into two candidates).
        for gx in range(int((x0 - TOUCH_PT) // GRID_PT), int((x1 + TOUCH_PT) // GRID_PT) + 1):
            for gy in range(int((y0 - TOUCH_PT) // GRID_PT), int((y1 + TOUCH_PT) // GRID_PT) + 1):
                grid[(gx, gy)].append(i)
    for cell in grid.values():
        for a in range(len(cell)):
            for b in range(a + 1, len(cell)):
                i, j = cell[a], cell[b]
                if _touching(paths[i].rect, paths[j].rect):
                    parent[find(i)] = find(j)
    groups: dict[int, list[Path]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(paths[i])
    return list(groups.values())


def _is_glyph(group: list[Path]) -> bool:
    if len(group) > MAX_PATHS:
        return False
    x0, y0, x1, y1 = _bbox(group)
    if (x1 - x0) > MAX_GLYPH_PT or (y1 - y0) > MAX_GLYPH_PT:
        return False
    if (x1 - x0) < MIN_GLYPH_PT or (y1 - y0) < MIN_GLYPH_PT:
        return False
    shaped = any(p.curved or p.closed or p.fill for p in group)
    return shaped or len(group) >= MIN_STRAIGHT_PATHS


def _forms(group: list[Path]) -> list[Form]:
    """The eight dihedral forms of a candidate, each relative to its own
    bbox origin so translation never matters."""
    x0, y0, x1, y1 = _bbox(group)
    w, h = x1 - x0, y1 - y0
    forms: list[Form] = []
    for t in range(8):
        rot, mirror = t % 4, t >= 4
        recs: Form = []
        for p in group:
            pts = []
            for (px, py) in p.pts:
                x, y = px - x0, py - y0
                ww, hh = w, h
                if mirror:
                    x = ww - x
                for _ in range(rot):      # 90° turns inside the box
                    x, y = hh - y, x
                    ww, hh = hh, ww
                pts.append((x, y))
            recs.append((p.fill, p.stroke, p.closed, pts))
        recs.sort(key=lambda r: (r[0], r[1], r[2], len(r[3]), min(r[3])))
        forms.append(recs)
    return forms


def _key(group: list[Path]) -> tuple:
    """Coarse bucket: path count and point-count multiset. Extents are
    deliberately excluded -- rounding them to a bucket has no tolerance,
    while same_shape's point matching already tolerates TOL_PT, so a size
    right at a rounding edge (9.49 vs 9.51 pt) would split matching shapes
    into different buckets and they would never be compared."""
    return (len(group), tuple(sorted(len(p.pts) for p in group)))


def _glyph(group: list[Path]) -> Glyph:
    return Glyph(rect=_bbox(group), forms=_forms(group), key=_key(group))


def _centre_in(rect, x, y) -> bool:
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def glyphs_on(page, region, words: list[Word]) -> list[Glyph]:
    """Every glyph candidate inside `region` (page points, visual frame),
    in page order. A candidate whose box contains a word's centre is
    text, not a symbol."""
    paths = [p for p in paths_on(page) if _small(p)]
    out: list[Glyph] = []
    centres = [(w.cx, w.cy) for w in words]
    for group in _candidates(paths):
        if not _is_glyph(group):
            continue
        rect = _bbox(group)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if not _centre_in(region, cx, cy):
            continue
        if any(_centre_in(rect, x, y) for x, y in centres):
            continue
        out.append(_glyph(group))
    return out


def _points_match(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> bool:
    if len(a) != len(b):
        return False
    free = list(b)
    for (ax, ay) in a:
        hit = next((i for i, (bx, by) in enumerate(free) if abs(ax - bx) <= TOL_PT and abs(ay - by) <= TOL_PT), None)
        if hit is None:
            return False
        free.pop(hit)
    return True


def _forms_match(fa: Form, fb: Form) -> bool:
    if len(fa) != len(fb):
        return False
    free = list(fb)
    for ra in fa:
        hit = next((i for i, rb in enumerate(free) if ra[:3] == rb[:3] and _points_match(ra[3], rb[3])), None)
        if hit is None:
            return False
        free.pop(hit)
    return True


def same_shape(a: Glyph, b: Glyph) -> bool:
    """The same drawn symbol under some rotation or mirror, within TOL_PT."""
    if a.key != b.key:
        return False
    return any(_forms_match(a.forms[0], f) for f in b.forms)


def signature_of(glyph: Glyph) -> str:
    """A stable id for a shape: sha256 of the lexicographically smallest of
    the eight forms after quantising to QUANT_PT, first 8 hex. The same
    file yields the same signature run after run."""
    canon = []
    for f in glyph.forms:
        canon.append(sorted((r[0], r[1], r[2], sorted((round(x / QUANT_PT), round(y / QUANT_PT)) for x, y in r[3])) for r in f))
    return hashlib.sha256(repr(min(canon)).encode()).hexdigest()[:8]


def cluster(glyphs: list[Glyph], min_instances: int = 3) -> list[ShapeCluster]:
    """Group by shape: each glyph joins the first exemplar in its bucket it
    matches, else starts a cluster. Largest first, then by first member's
    position for a stable order."""
    buckets: dict[tuple, list[list[Glyph]]] = defaultdict(list)
    for g in glyphs:
        for members in buckets[g.key]:
            if same_shape(members[0], g):
                members.append(g)
                break
        else:
            buckets[g.key].append([g])
    out = [ShapeCluster(signature=signature_of(m[0]), members=m)
           for ms in buckets.values() for m in ms if len(m) >= min_instances]
    out.sort(key=lambda c: (-len(c.members), c.members[0].rect))
    return out


def matches_of(glyph: Glyph, glyphs: list[Glyph]) -> list[Glyph]:
    """Every glyph the same shape as `glyph` -- itself included when it is
    among `glyphs`."""
    return [g for g in glyphs if same_shape(glyph, g)]


def glyph_in(page, rect, words: list[Word]) -> Glyph | None:
    """The one candidate whose paths all lie inside `rect` (page points,
    visual frame). None when the box holds no full-tone glyph -- the
    caller falls back to raster matching."""
    x0, y0, x1, y1 = rect
    paths = [p for p in paths_on(page) if _small(p)
             and p.rect[0] >= x0 and p.rect[1] >= y0 and p.rect[2] <= x1 and p.rect[3] <= y1]
    groups = [g for g in _candidates(paths) if _is_glyph(g)]
    if not groups:
        return None
    group = max(groups, key=len)
    centres = [(w.cx, w.cy) for w in words]
    if any(_centre_in(_bbox(group), x, y) for x, y in centres):
        return None
    return _glyph(group)
