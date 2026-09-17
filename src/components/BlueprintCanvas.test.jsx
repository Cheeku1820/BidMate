import { describe, expect, it, vi } from "vitest";
import { act, render } from "@testing-library/react";
import BlueprintCanvas from "./BlueprintCanvas.jsx";

// jsdom has no ResizeObserver; the canvas uses one to track its viewport.
class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", StubResizeObserver);

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
