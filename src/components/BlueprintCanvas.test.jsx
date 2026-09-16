import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
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
