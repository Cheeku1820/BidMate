import { describe, expect, it } from "vitest";
import { paperSize, toPaper, fromPaper, pointToPaper, paperDistanceToPoints } from "./sheetGeometry.js";

const D = { widthPt: 2592, heightPt: 1728 };   // 36 x 24 in, 3:2
const NONE = { widthPt: 0, heightPt: 0 };

describe("sheetGeometry", () => {
  it("gives the paper the page's real aspect", () => {
    expect(paperSize(D)).toEqual({ w: 1000, h: 667 });
    expect(paperSize({ widthPt: 1000, heightPt: 750 })).toEqual({ w: 1000, h: 750 });
    expect(paperSize(NONE)).toEqual({ w: 1000, h: 750 });
  });
  it("rescales only y, and round-trips", () => {
    expect(toPaper({ x: 500, y: 375 }, D)).toEqual({ x: 500, y: 333.5 });
    const p = fromPaper(toPaper({ x: 120, y: 700 }, D), D);
    expect(p.x).toBeCloseTo(120); expect(p.y).toBeCloseTo(700);
    expect(pointToPaper([500, 375], D)).toEqual([500, 333.5]);
    expect(toPaper({ x: 500, y: 375 }, NONE)).toEqual({ x: 500, y: 375 });
  });
  it("converts a paper distance to page points along x", () => {
    expect(paperDistanceToPoints(100, D)).toBeCloseTo(259.2);
    expect(paperDistanceToPoints(100, NONE)).toBe(0);
  });
});
