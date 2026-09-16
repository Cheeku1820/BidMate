"""tiles.py cuts one sheet into a 512 px tile pyramid, in the visual
frame -- the same frame the engine's placements are in (page_frame.py),
so a stored marker maps to a tile pixel exactly."""

import math

import pymupdf
import pytest

from app.engine import tiles


def _pdf(tmp_path, w_in, h_in, rotate=0):
    doc = pymupdf.open()
    page = doc.new_page(width=w_in * 72, height=h_in * 72)
    page.draw_rect(pymupdf.Rect(36, 36, w_in * 72 - 36, h_in * 72 - 36), color=(0, 0, 0), width=2)
    # a filled square in the visual top-left quadrant, so a test can find it in a tile
    page.draw_rect(pymupdf.Rect(72, 72, 144, 144), color=(0, 0, 0), fill=(0, 0, 0))
    if rotate:
        page.set_rotation(rotate)
    p = tmp_path / "t.pdf"
    doc.save(p)
    return str(p)


def test_level_zero_fits_one_tile_and_levels_double_to_150_dpi():
    lv = tiles.levels_for(36 * 72, 24 * 72)      # ARCH D, landscape
    assert lv[0].cols == 1 and lv[0].rows == 1
    for a, b in zip(lv, lv[1:]):
        assert math.isclose(b.scale, a.scale * 2)
    assert 72 * lv[-1].scale >= tiles.TARGET_DPI
    assert 72 * lv[-2].scale < tiles.TARGET_DPI
    assert lv[-1].cols == math.ceil(36 * 72 * lv[-1].scale / tiles.TILE)


def test_e_size_reaches_150_dpi_at_a_deeper_level_than_d_size():
    assert len(tiles.levels_for(48 * 72, 36 * 72)) > len(tiles.levels_for(24 * 72, 18 * 72))


def test_arch_d_and_arch_e_both_reach_150_dpi_at_z_4():
    """docs/specs/drawing-behind-the-markers.md §3 used to say "typically
    z = 3 for D-size, 4 for E-size" -- wrong on both counts. ARCH D (24 x
    36 in) and ARCH E (36 x 48 in) both land on z = 4: each doubling
    roughly doubles dpi, so the one-size-larger E sheet needs the same
    level D does once D has already overshot 150 dpi at z = 4."""
    d = tiles.levels_for(24 * 72, 36 * 72)
    e = tiles.levels_for(36 * 72, 48 * 72)
    assert d[-1].z == 4 and 72 * d[-1].scale >= tiles.TARGET_DPI
    assert e[-1].z == 4 and 72 * e[-1].scale >= tiles.TARGET_DPI


def test_render_writes_every_tile_and_the_thumbnail(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 36, 24), 0, str(out))
    assert ts.width_pt == 36 * 72 and ts.height_pt == 24 * 72
    assert "thumb.png" in ts.files
    for lv in ts.levels:
        for x in range(lv.cols):
            for y in range(lv.rows):
                f = f"{lv.z}/{x}_{y}.png"
                assert f in ts.files and (out / f).exists()
    interior = pymupdf.Pixmap(str(out / f"{ts.levels[-1].z}/0_0.png"))
    assert (interior.width, interior.height) == (tiles.TILE, tiles.TILE)
    thumb = pymupdf.Pixmap(str(out / "thumb.png"))
    assert thumb.width == tiles.THUMB_W
    assert len(ts.files) == 1 + sum(lv.cols * lv.rows for lv in ts.levels)


def test_edge_tiles_are_clipped_not_padded(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 36, 24), 0, str(out))
    lv = ts.levels[-1]
    edge = pymupdf.Pixmap(str(out / f"{lv.z}/{lv.cols - 1}_{lv.rows - 1}.png"))
    # The page is landscape (36in wide, 24in tall), so width is the long
    # edge levels_for scales against: by construction (level 0's scale is
    # TILE / long_edge, each further level doubling it), width_pt * scale
    # is an exact multiple of TILE at every level, so the last COLUMN is
    # always a full TILE wide -- verified empirically (36*72*scale ==
    # 8192.0 exactly at the finest level here, vs. 24*72*scale ==
    # 5461.33...). Height is the short edge and does not divide evenly, so
    # the corner tile is genuinely clipped in height, not width.
    assert edge.width == tiles.TILE
    expected_h = round(24 * 72 * lv.scale) - (lv.rows - 1) * tiles.TILE
    assert abs(edge.height - expected_h) <= 1 and edge.height < tiles.TILE


def test_a_rotated_page_renders_in_the_visual_frame(tmp_path):
    out = tmp_path / "out"
    ts = tiles.render_sheet(_pdf(tmp_path, 24, 36, rotate=90), 0, str(out))
    assert ts.width_pt == 36 * 72 and ts.height_pt == 24 * 72     # visual: landscape
    # Verified empirically (scratch: (Rect(72,72,144,144) * page.rotation_matrix)
    # for a 24x36in page rotated 90): PyMuPDF rotates the page clockwise for
    # display, so a mark at unrotated (72..144, 72..144) lands at visual
    # x in [width_pt - 144, width_pt - 72], y in [72, 144] -- visual top-RIGHT.
    # The filled square drawn at unrotated (72..144, 72..144) lands, after a
    # 90 degree rotation, in the visual top-right; level 0 is one tile, so
    # sample it there.
    pix = pymupdf.Pixmap(str(out / "0/0_0.png"))
    s = ts.levels[0].scale
    x, y = int((36 * 72 - 108) * s), int(108 * s)
    assert pix.pixel(x, y)[0] < 128        # dark
    assert pix.pixel(int(108 * s), int(108 * s))[0] > 200   # top-left is white


def test_a_page_that_cannot_render_raises(tmp_path):
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"%PDF-1.4 nope")
    with pytest.raises(Exception):
        tiles.render_sheet(str(p), 0, str(tmp_path / "out"))
