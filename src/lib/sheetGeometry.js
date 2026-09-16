/* sheetGeometry.js — the one place stored marker space meets the paper.
   Markers are stored in a 1000 x 750 sheet space (x normalised against the
   page's width, y against its height -- ingest.py). A page is rarely 4:3,
   so the paper the canvas draws takes the page's real aspect and y is
   rescaled here, at draw time. Nothing counted moves. */
export const SHEET_W = 1000;
export const SHEET_H = 750;

export function paperSize(sheet) {
  const w = Number(sheet?.widthPt || 0), h = Number(sheet?.heightPt || 0);
  if (!w || !h) return { w: SHEET_W, h: SHEET_H };
  return { w: SHEET_W, h: Math.round((SHEET_W * h) / w) };
}
const ky = (sheet) => paperSize(sheet).h / SHEET_H;
export function toPaper(p, sheet) { return { x: p.x, y: p.y * ky(sheet) }; }
export function fromPaper(p, sheet) { return { x: p.x, y: p.y / ky(sheet) }; }
export function pointToPaper([x, y], sheet) { return [x, y * ky(sheet)]; }
export function paperDistanceToPoints(d, sheet) {
  const w = Number(sheet?.widthPt || 0);
  return w ? (d * w) / SHEET_W : 0;
}
