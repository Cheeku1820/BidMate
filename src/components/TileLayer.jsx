/* ============================================================
   TileLayer.jsx — the real page under the takeoff markers.

   The worker cuts each rendered sheet into a 512 px tile pyramid; this
   lays those tiles out in paper units, inside the same transformed
   `.sheetpaper` the marker SVG sits in, so a marker drawn at (x, y)
   lands on the pixel the engine counted. Pure helpers (`levelFor`,
   `gridFor`, `visibleTiles`) do the arithmetic and are tested alone.

   At level z the page's LONG edge is exactly 512 · 2^z px, so one tile
   spans max(paper.w, paper.h) / 2^z paper units on both axes; on a
   landscape page the last column is a full tile and only the rows are
   clipped (tiles.py does the same arithmetic on the engine side).
   ============================================================ */
import { useState } from "react";
import { paperSize, SHEET_W } from "../lib/sheetGeometry.js";

const TILE = 512;

/** Smallest level whose long-edge width covers the page as drawn on
 *  screen, capped at the finest level the worker rendered. A sheet with
 *  no finest level yet (maxZoom null) has only level 0 to offer. */
export function levelFor(viewScale, maxZoom) {
  const cap = maxZoom ?? 0;
  const onScreen = SHEET_W * viewScale;
  let z = 0;
  while (TILE * 2 ** z < onScreen && z < cap) z += 1;
  return Math.min(z, cap);
}

/** The level's grid in paper units. */
export function gridFor(z, paper) {
  const long = Math.max(paper.w, paper.h);
  const tilePaper = long / 2 ** z;
  return { z, cols: Math.ceil(paper.w / tilePaper), rows: Math.ceil(paper.h / tilePaper), tilePaper };
}

/** Tiles of `grid` intersecting `viewport` (paper units), plus a one-tile
 *  margin on every side, each with its clipped paper rectangle. */
export function visibleTiles(viewport, grid, paper) {
  const t = grid.tilePaper;
  // The first tile touching an edge is floor(edge / t); the last one is
  // ceil(edge / t) - 1, so an edge sitting exactly on a tile boundary
  // does not pull in the tile beyond it. Then one tile of margin.
  const x0 = Math.max(0, Math.floor(viewport.x / t) - 1);
  const x1 = Math.min(grid.cols - 1, Math.ceil((viewport.x + viewport.w) / t));
  const y0 = Math.max(0, Math.floor(viewport.y / t) - 1);
  const y1 = Math.min(grid.rows - 1, Math.ceil((viewport.y + viewport.h) / t));
  const out = [];
  for (let y = y0; y <= y1; y += 1) {
    for (let x = x0; x <= x1; x += 1) {
      out.push({
        z: grid.z,
        x,
        y,
        left: x * t,
        top: y * t,
        width: Math.min(t, paper.w - x * t),
        height: Math.min(t, paper.h - y * t),
      });
    }
  }
  return out;
}

/** One tile. A load error is retried once after 2 s, then left blank --
 *  the sheet-level state carries any copy, never a tile. */
function Tile({ sheet, t }) {
  const [attempt, setAttempt] = useState(0);
  const src = `/api/sheets/${sheet.id}/tiles/${t.z}/${t.x}/${t.y}.png${attempt ? `?r=${attempt}` : ""}`;
  return (
    <img
      className="tile"
      alt=""
      src={src}
      draggable={false}
      style={{ left: t.left, top: t.top, width: t.width, height: t.height }}
      onError={() => {
        if (attempt === 0) setTimeout(() => setAttempt(1), 2000);
      }}
    />
  );
}

export default function TileLayer({ sheet, view, size }) {
  const paper = paperSize(sheet);
  if (sheet.renderStatus !== "rendered") {
    // Blank paper carrying only the sheet's own identity and what is
    // happening to it. The copy is the sheet's render state, on its own
    // axis -- never one of the four review labels.
    return (
      <div className="tilelayer tilelayer--blank" style={{ width: paper.w, height: paper.h }}>
        <div className="tilelayer__note">
          <div>
            {sheet.number}
            {sheet.title ? ` — ${sheet.title}` : ""}
          </div>
          <div>{sheet.renderStatus === "failed" ? sheet.renderError : "Drawing the sheet…"}</div>
        </div>
      </div>
    );
  }
  const z = levelFor(view.scale, sheet.maxZoom);
  const viewport = { x: -view.tx / view.scale, y: -view.ty / view.scale, w: size.w / view.scale, h: size.h / view.scale };
  const tiles = visibleTiles(viewport, gridFor(z, paper), paper);
  // Level 0 always sits underneath, so zooming never flashes to white
  // while the finer tiles load.
  const backdrop = visibleTiles({ x: 0, y: 0, w: paper.w, h: paper.h }, gridFor(0, paper), paper);
  return (
    <div className="tilelayer" style={{ width: paper.w, height: paper.h }}>
      {backdrop.map((t) => (
        <Tile key={`b${t.x}_${t.y}`} sheet={sheet} t={t} />
      ))}
      {z > 0 && tiles.map((t) => <Tile key={`${t.z}_${t.x}_${t.y}`} sheet={sheet} t={t} />)}
    </div>
  );
}
