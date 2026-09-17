import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render } from "@testing-library/react";
import BlueprintCanvas from "./BlueprintCanvas.jsx";
import { STATUS } from "../lib/vocabulary.js";

// jsdom has no ResizeObserver; the canvas uses one to track its viewport.
class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", StubResizeObserver);

// jsdom (still, as of v25) has no PointerEvent constructor.
// @testing-library/dom's fireEvent.pointerDown/Move/Up construct one via
// `window.PointerEvent`, and when that's missing it silently falls back
// to a bare `Event`, which drops clientX/clientY/pointerId entirely --
// the drag handlers under test read exactly those. MouseEvent is fully
// implemented in jsdom and carries clientX/clientY natively, so a thin
// PointerEvent stand-in built on it gives the handlers real coordinates.
class StubPointerEvent extends MouseEvent {
  constructor(type, init = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
  }
}
vi.stubGlobal("PointerEvent", StubPointerEvent);

const LAYERS = { detected: true, approved: true, rejected: true, measurements: true, warnings: true, legend: false };

function canvas(sheet, items, extra = {}) {
  return render(
    <BlueprintCanvas
      sheet={sheet}
      items={items}
      selectedId={null}
      onSelect={() => {}}
      layers={LAYERS}
      tool="pan"
      onCalibrate={() => {}}
      remoteSelections={[]}
      searchTerm=""
      {...extra}
    />
  );
}

const THREE_TWO = { id: "s1", number: "E2.1", title: "", widthPt: 2592, heightPt: 1728, renderStatus: "pending", renderError: "", maxZoom: null, scale: "" };

describe("BlueprintCanvas on real paper", () => {
  it("draws a marker stored at the sheet's centre at the paper's centre on a 3:2 page", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "r", quantity: 1, unit: "ea", placements: [[500, 375]] }];
    const { container } = canvas(THREE_TWO, items);
    const g = container.querySelector('g[transform^="translate"]');
    expect(g.getAttribute("transform")).toBe("translate(500 333.5)");
    const paper = container.querySelector(".sheetpaper");
    expect(paper.style.width).toBe("1000px");
    expect(paper.style.height).toBe("667px");
    const svg = container.querySelector(".sheetpaper svg");
    expect(svg.getAttribute("viewBox")).toBe("0 0 1000 667");
  });

  it("keeps the 1000 x 750 paper when the sheet has no page dimensions", () => {
    const sheet = { ...THREE_TWO, widthPt: 0, heightPt: 0 };
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "r", quantity: 1, unit: "ea" }];
    const { container } = canvas(sheet, items);
    expect(container.querySelector('g[transform^="translate"]').getAttribute("transform")).toBe("translate(500 375)");
    expect(container.querySelector(".sheetpaper").style.height).toBe("750px");
  });

  it("rescales a measured run's polyline and its placement dots the same way as the markers", () => {
    const items = [
      { id: "m1", sheetId: "s1", status: "missing", symbol: "conduit", name: "run", quantity: 40, unit: "ft", path: [[100, 150], [300, 150]] },
      { id: "i1", sheetId: "s1", x: 200, y: 300, status: "ready", symbol: "receptacle", name: "r", quantity: 2, unit: "ea", placements: [[200, 300], [400, 600]] },
    ];
    const { container } = canvas(THREE_TWO, items, { selectedId: "i1" });
    const poly = container.querySelector("polyline");
    expect(poly.getAttribute("points")).toBe("100,133.4 300,133.4");
    const dots = [...container.querySelectorAll('g[aria-hidden="true"] circle')].map((c) => [c.getAttribute("cx"), c.getAttribute("cy")]);
    expect(dots).toEqual([["200", "266.8"], ["400", "533.6"]]);
  });

  it("puts the tile layer under the marker svg, inside the paper", () => {
    const { container } = canvas({ ...THREE_TWO, renderStatus: "rendered", maxZoom: 2 }, []);
    const paper = container.querySelector(".sheetpaper");
    expect(paper.children[0].className).toContain("tilelayer");
    expect(paper.children[1].tagName.toLowerCase()).toBe("svg");
  });

  it("still names the sheet on blank paper while the drawing is pending", () => {
    const { getByText } = canvas(THREE_TWO, []);
    expect(getByText(/E2\.1/)).toBeInTheDocument();
  });
});

/* Selection can arrive from the table, from "Open next issue", or from
   J/K, with the marker anywhere on the page (DESIGN.md, "Blueprint and
   table synchronization": selecting a row centers the blueprint on that
   marker). The viewport is jsdom's default 900 x 600; zooming in four
   steps through the same window event the toolbar uses pushes the far
   corner of the page off screen. */
function stageTransform(container) {
  const m = container.querySelector(".stage").style.transform.match(/translate\(([-\d.]+)px, ([-\d.]+)px\) scale\(([-\d.]+)\)/);
  return { tx: Number(m[1]), ty: Number(m[2]), scale: Number(m[3]) };
}
function zoomIn(times) {
  for (let i = 0; i < times; i += 1) {
    act(() => {
      window.dispatchEvent(new CustomEvent("canvas-cmd", { detail: { type: "in" } }));
    });
  }
}

describe("BlueprintCanvas brings the selected marker into view", () => {
  const far = { id: "i2", sheetId: "s1", x: 950, y: 700, status: "attention", symbol: "receptacle", name: "far", quantity: 1, unit: "ea", placements: [[950, 700]] };
  const mid = { id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "mid", quantity: 1, unit: "ea", placements: [[500, 375]] };

  it("pans so an off-screen selection sits at the centre, keeping the zoom", () => {
    const { container, rerender } = canvas(THREE_TWO, [mid, far]);
    zoomIn(4);
    const before = stageTransform(container);
    // far corner of a 3:2 page: paper (950, 622.6); off screen at this zoom
    expect(before.tx + 950 * before.scale).toBeGreaterThan(900);
    rerender(
      <BlueprintCanvas sheet={THREE_TWO} items={[mid, far]} selectedId="i2" onSelect={() => {}} layers={LAYERS} tool="pan" onCalibrate={() => {}} remoteSelections={[]} searchTerm="" />,
    );
    const after = stageTransform(container);
    expect(after.scale).toBe(before.scale);
    expect(after.tx + 950 * after.scale).toBeCloseTo(450, 0);
    expect(after.ty + (700 * (667 / 750)) * after.scale).toBeCloseTo(300, 0);
  });

  it("leaves the view alone when the selected marker is already visible", () => {
    const { container, rerender } = canvas(THREE_TWO, [mid, far]);
    zoomIn(2);
    const before = stageTransform(container);
    rerender(
      <BlueprintCanvas sheet={THREE_TWO} items={[mid, far]} selectedId="i1" onSelect={() => {}} layers={LAYERS} tool="pan" onCalibrate={() => {}} remoteSelections={[]} searchTerm="" />,
    );
    expect(stageTransform(container)).toEqual(before);
  });
});

describe("boxed placements and symbol matches", () => {
  const SHEET = { ...THREE_TWO };

  it("outlines a selected item's boxed placements and rings its point placements", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 100, y: 100, status: "ready", symbol: "receptacle", name: "r", quantity: 2, unit: "ea",
                     placements: [[100, 100, 20, 10], [300, 100]] }];
    const { container } = canvas(SHEET, items, { selectedId: "i1" });
    const box = container.querySelector("rect.placement-box");
    expect(box).not.toBeNull();
    expect(box.getAttribute("width")).toBe("20");
    expect(Number(box.getAttribute("height"))).toBeCloseTo(10 * (667 / 750), 1);
    expect(container.querySelectorAll("circle.placement-ring").length).toBe(1);
  });

  it("draws result boxes in blueprint blue regardless of layers", () => {
    const match = { status: "found", box: [100, 100, 20, 10], matches: [[100, 100, 20, 10], [300, 100, 20, 10]] };
    const { container } = canvas(SHEET, [], { match, layers: { ...LAYERS, detected: false, approved: false } });
    const boxes = container.querySelectorAll("rect.matchbox");
    expect(boxes.length).toBe(2);
    expect(boxes[0].getAttribute("stroke")).toBe("var(--blue)");
    expect(boxes[0].getAttribute("fill")).toBe("none");
  });

  // The canvas's initial view is whatever fit() computed against the
  // jsdom-default 900x600 viewport (the ResizeObserver stub never fires),
  // not the identity transform -- so the expected sheet-unit box is
  // derived from the same view + fromPaper mapping the component itself
  // uses, read back through stageTransform, rather than a hand-computed
  // number that would silently drift if fit()'s math ever changed.
  it("hands a dragged box up in sheet units", () => {
    const onDrawBox = vi.fn();
    const { container } = canvas(SHEET, [], { tool: "match", onDrawBox });
    const vp = container.querySelector(".viewport");
    vp.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 667 });
    act(() => { fireEvent.pointerDown(vp, { clientX: 100, clientY: 100, pointerId: 1 }); });
    act(() => { fireEvent.pointerMove(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    act(() => { fireEvent.pointerUp(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    expect(onDrawBox).toHaveBeenCalledTimes(1);

    const { tx, ty, scale } = stageTransform(container);
    const ky = 667 / 750;
    const px0 = (100 - tx) / scale, px1 = (140 - tx) / scale;
    const py0 = (100 - ty) / scale, py1 = (120 - ty) / scale;
    const expected = {
      x: Math.round((px0 + px1) / 2),
      y: Math.round(((py0 + py1) / 2) / ky),
      w: Math.round(px1 - px0),
      h: Math.round((py1 - py0) / ky),
    };
    expect(onDrawBox.mock.calls[0][0]).toEqual(expected);
  });

  it("clears an in-progress drag on Escape without calling onDrawBox", () => {
    const onDrawBox = vi.fn();
    const { container } = canvas(SHEET, [], { tool: "match", onDrawBox });
    const vp = container.querySelector(".viewport");
    vp.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 667 });
    act(() => { fireEvent.pointerDown(vp, { clientX: 100, clientY: 100, pointerId: 1 }); });
    act(() => { fireEvent.pointerMove(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    expect(container.querySelector("rect.matchbox")).not.toBeNull();
    act(() => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(container.querySelector("rect.matchbox")).toBeNull();
    act(() => { fireEvent.pointerUp(vp, { clientX: 140, clientY: 120, pointerId: 1 }); });
    expect(onDrawBox).not.toHaveBeenCalled();
  });
});

/* Task 14: the marker no longer covers the symbol it sits on -- the
   status colour becomes the outline of the glyph's own box (plus a
   faint interior tint) rather than a white disc with the app's glyph
   drawn on top. The 20 x 20 sheet-unit box used below scales to well
   over MIN_MARKER on THREE_TWO's 667/750 ky, so these assert the real
   scaled numbers rather than colliding with the minimum-size floor
   exercised separately below. */
describe("point markers outline the glyph's box instead of covering it", () => {
  const KY = 667 / 750;

  it("renders a marker-box sized to the placement, with no white disc and no glyph inside it", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "r", quantity: 1, unit: "ea", placements: [[500, 375, 20, 20]] }];
    const { container } = canvas(THREE_TWO, items);
    const g = container.querySelector('g[transform^="translate"]');
    const box = g.querySelector("rect.marker-box");
    expect(box).not.toBeNull();
    expect(box.getAttribute("width")).toBe("20");
    expect(Number(box.getAttribute("height"))).toBeCloseTo(20 * KY, 1);
    expect(box.getAttribute("stroke")).toBe(STATUS.ready.color);
    expect(box.getAttribute("fill-opacity")).toBe("0.1");
    // no white disc, and no SymbolGlyph (a receptacle draws two <line>s)
    // on the sheet -- the type channel now lives in the tooltip only.
    expect(g.querySelector('circle[fill="#fff"]')).toBeNull();
    expect(g.querySelector("line")).toBeNull();
  });

  it("renders a marker-ring, not a marker-box, for a placement with no extent", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "switch", name: "s", quantity: 1, unit: "ea", placements: [[500, 375]] }];
    const { container } = canvas(THREE_TWO, items);
    const g = container.querySelector('g[transform^="translate"]');
    expect(g.querySelector("circle.marker-ring")).not.toBeNull();
    expect(g.querySelector("rect.marker-box")).toBeNull();
  });

  it("floors a tiny box at MIN_MARKER (12) on each side, centred", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "attention", symbol: "receptacle", name: "r", quantity: 1, unit: "ea", placements: [[500, 375, 4, 3]] }];
    const { container } = canvas(THREE_TWO, items);
    const box = container.querySelector("rect.marker-box");
    expect(Number(box.getAttribute("width"))).toBeGreaterThanOrEqual(12);
    expect(Number(box.getAttribute("height"))).toBeGreaterThanOrEqual(12);
    expect(box.getAttribute("x")).toBe(String(-Number(box.getAttribute("width")) / 2));
    expect(box.getAttribute("y")).toBe(String(-Number(box.getAttribute("height")) / 2));
  });

  it("gives the selected item's marker-box the selected fill-opacity", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "ready", symbol: "receptacle", name: "r", quantity: 1, unit: "ea", placements: [[500, 375, 20, 20]] }];
    const { container } = canvas(THREE_TWO, items, { selectedId: "i1" });
    const box = container.querySelector("rect.marker-box");
    expect(box.getAttribute("fill-opacity")).toBe("0.18");
  });

  it("shows the item name and status label in the hover tooltip", () => {
    const items = [{ id: "i1", sheetId: "s1", x: 500, y: 375, status: "attention", symbol: "receptacle", name: "20A duplex receptacle", quantity: 1, unit: "ea", placements: [[500, 375, 20, 20]] }];
    const { container } = canvas(THREE_TWO, items);
    const g = container.querySelector('g[transform^="translate"]');
    fireEvent.mouseEnter(g);
    const tip = container.querySelector(".tooltip");
    expect(tip).not.toBeNull();
    expect(tip.textContent).toContain("20A duplex receptacle");
    expect(tip.textContent).toContain(STATUS.attention.label);
  });
});
