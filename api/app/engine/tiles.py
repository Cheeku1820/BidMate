"""The rendered page behind the markers: a tile pyramid per sheet, cut
with PyMuPDF in the visual frame -- the same frame the engine's
placements are in (page_frame.py), so a stored marker maps to a tile
pixel exactly. No storage here: the worker uploads what this writes."""

from __future__ import annotations

import math
import os

import pymupdf

from .contracts import Level, TileSet
from .documents import _open_checked

TILE = 512
TARGET_DPI = 150
THUMB_W = 240


def levels_for(width_pt: float, height_pt: float) -> list[Level]:
    """The pyramid for one page: level 0 has the long edge fit inside a
    single TILE px tile, and each further level doubles the scale until
    72 * scale reaches TARGET_DPI -- pure geometry, no PDF involved, so
    the worker (or a test) can plan storage without opening the file."""
    long_edge = max(width_pt, height_pt)
    levels: list[Level] = []
    z = 0
    while True:
        scale = TILE * (2**z) / long_edge
        levels.append(
            Level(
                z=z,
                cols=math.ceil(width_pt * scale / TILE),
                rows=math.ceil(height_pt * scale / TILE),
                scale=scale,
            )
        )
        if 72 * scale >= TARGET_DPI:
            return levels
        z += 1


def _tile_clip(rect: pymupdf.Rect, x: int, y: int, scale: float) -> pymupdf.Rect:
    """The clip for tile (x, y) at `scale`, computed in pixel space and
    converted back to points. A clip built directly in points (TILE /
    scale) can round to 511 or 513 px once get_pixmap rasterizes it; a
    clip built from whole pixel coordinates and divided by scale does
    not have that problem, so the finest level's interior tiles land on
    exactly TILE px."""
    px = pymupdf.Rect(x * TILE, y * TILE, (x + 1) * TILE, (y + 1) * TILE) / scale
    return pymupdf.Rect(
        rect.x0 + px.x0,
        rect.y0 + px.y0,
        min(rect.x0 + px.x1, rect.x1),
        min(rect.y0 + px.y1, rect.y1),
    )


def render_sheet(path: str, page_index: int, out_dir: str) -> TileSet:
    """Cut one page into its tile pyramid plus a thumbnail, writing PNGs
    under out_dir and returning what got written. One pixmap live at a
    time -- rendered, saved, dropped -- so a large sheet's finest level
    does not hold every tile in memory at once."""
    doc = _open_checked(path)
    try:
        page = doc[page_index]
        rect = page.rect  # visual frame -- see page_frame.py
        width_pt, height_pt = rect.width, rect.height
        levels = levels_for(width_pt, height_pt)
        files: list[str] = []
        for lv in levels:
            os.makedirs(os.path.join(out_dir, str(lv.z)), exist_ok=True)
            for x in range(lv.cols):
                for y in range(lv.rows):
                    clip = _tile_clip(rect, x, y, lv.scale)
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(lv.scale, lv.scale), clip=clip, alpha=False)
                    rel = f"{lv.z}/{x}_{y}.png"
                    pix.save(os.path.join(out_dir, rel))
                    files.append(rel)
                    del pix

        thumb_scale = THUMB_W / width_pt
        thumb_pix = page.get_pixmap(matrix=pymupdf.Matrix(thumb_scale, thumb_scale), alpha=False)
        thumb_pix.save(os.path.join(out_dir, "thumb.png"))
        del thumb_pix
        files.append("thumb.png")

        return TileSet(levels=levels, thumb="thumb.png", files=files, width_pt=width_pt, height_pt=height_pt)
    finally:
        doc.close()
