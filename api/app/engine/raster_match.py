"""Find every copy of a boxed symbol on a page render (B3b spec §6).

The raster path of 'find every one like this': when the box holds no
vector glyph -- a scanned sheet, a placed image -- the page is rendered
once and the box's pixels are slid over it with normalised
cross-correlation. Deterministic and constant-driven, like glyphs.py;
the threshold is a measured value with a test, not a tuned one.

OpenCV is imported here and nowhere else; app.main must never reach
this module (test_api_import_boundary.py).
"""
from __future__ import annotations

import cv2
import numpy as np
import pymupdf

MATCH_DPI = 200
MATCH_THRESHOLD = 0.80
MAX_PIXELS = 40_000_000
_ROTATIONS = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)


def _render(page) -> tuple[np.ndarray, float]:
    """Greyscale pixels of the visual page and the scale (px per point)."""
    scale = MATCH_DPI / 72
    if page.rect.width * page.rect.height * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / (page.rect.width * page.rect.height)) ** 0.5
    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return img, scale


def _peaks(score: np.ndarray, tw: int, th: int) -> list[tuple[int, int, float]]:
    """Every location at or above the threshold, strongest first, with
    non-maximum suppression at half the template's size."""
    ys, xs = np.where(score >= MATCH_THRESHOLD)
    cands = sorted(((float(score[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
    kept: list[tuple[int, int, float]] = []
    for s, x, y in cands:
        if all(abs(x - kx) >= tw / 2 or abs(y - ky) >= th / 2 for kx, ky, _ in kept):
            kept.append((x, y, s))
    return kept


def find_on_render(path: str, page_index: int, rect) -> list[tuple[float, float, float, float]]:
    """Page-point rects (visual frame) of every place the pixels inside
    `rect` recur on the page, at 0/90/180/270°, the box itself included.
    Overlapping hits across rotations collapse to the strongest."""
    doc = pymupdf.open(path)
    page = doc[page_index]
    img, scale = _render(page)
    x0, y0, x1, y1 = (int(round(v * scale)) for v in rect)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    template = img[y0:y1, x0:x1]
    if template.size == 0 or min(template.shape) < 4:
        return []
    hits: list[tuple[int, int, int, int, float]] = []   # x, y, w, h, score
    for rot in _ROTATIONS:
        t = template if rot is None else cv2.rotate(template, rot)
        th, tw = t.shape
        if th > img.shape[0] or tw > img.shape[1]:
            continue
        score = cv2.matchTemplate(img, t, cv2.TM_CCOEFF_NORMED)
        hits += [(x, y, tw, th, s) for x, y, s in _peaks(score, tw, th)]
    hits.sort(key=lambda h: -h[4])
    kept: list[tuple[int, int, int, int, float]] = []
    for h in hits:
        cx, cy = h[0] + h[2] / 2, h[1] + h[3] / 2
        if all(abs(cx - (k[0] + k[2] / 2)) >= h[2] / 2 or abs(cy - (k[1] + k[3] / 2)) >= h[3] / 2 for k in kept):
            kept.append(h)
    return [(x / scale, y / scale, (x + w) / scale, (y + h) / scale) for x, y, w, h, _ in kept]
