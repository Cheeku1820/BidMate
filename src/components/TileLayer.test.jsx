import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TileLayer, { levelFor, visibleTiles, gridFor } from "./TileLayer.jsx";

const D = { id: "s1", number: "E2.1", widthPt: 2592, heightPt: 1728, renderStatus: "rendered", renderError: "", maxZoom: 3 };

describe("levelFor", () => {
  it("picks the smallest level whose width covers the on-screen page, capped", () => {
    expect(levelFor(0.4, 3)).toBe(0);   // 400 px on screen -> level 0 (512)
    expect(levelFor(1.1, 3)).toBe(2);   // 1100 px -> 2048
    expect(levelFor(9, 3)).toBe(3);     // capped
  });
  it("falls back to level 0 when the sheet reports no finest level", () => {
    expect(levelFor(4, null)).toBe(0);
    expect(levelFor(4, undefined)).toBe(0);
  });
});

describe("gridFor / visibleTiles", () => {
  it("derives the grid from the paper aspect and clips edge tiles", () => {
    const g = gridFor(2, { w: 1000, h: 667 });          // level 2: long edge 2048 px -> 4 cols
    expect(g).toEqual({ z: 2, cols: 4, rows: 3, tilePaper: 250 });
    const tiles = visibleTiles({ x: 0, y: 0, w: 1000, h: 667 }, g, { w: 1000, h: 667 });
    expect(tiles).toHaveLength(12);
    const last = tiles.find((t) => t.x === 3 && t.y === 2);
    expect(last).toMatchObject({ left: 750, top: 500, width: 250, height: 167 });
  });
  it("returns only tiles intersecting the viewport, with a one-tile margin", () => {
    const g = gridFor(3, { w: 1000, h: 667 });          // 8 cols
    const tiles = visibleTiles({ x: 400, y: 300, w: 100, h: 100 }, g, { w: 1000, h: 667 });
    const xs = new Set(tiles.map((t) => t.x));
    expect(Math.min(...xs)).toBe(2); expect(Math.max(...xs)).toBe(4);
  });
  it("uses the long edge for a portrait page, so the last row is the full tile and columns are clipped", () => {
    const g = gridFor(1, { w: 1000, h: 1500 });         // long edge is h: tile = 750 paper units
    expect(g).toEqual({ z: 1, cols: 2, rows: 2, tilePaper: 750 });
    const tiles = visibleTiles({ x: 0, y: 0, w: 1000, h: 1500 }, g, { w: 1000, h: 1500 });
    expect(tiles.find((t) => t.x === 1 && t.y === 1)).toMatchObject({ left: 750, top: 750, width: 250, height: 750 });
  });
});

describe("TileLayer", () => {
  it("renders the backdrop and the visible tiles for a rendered sheet", () => {
    const { container } = render(<TileLayer sheet={D} view={{ scale: 0.8, tx: 0, ty: 0 }} size={{ w: 800, h: 534 }} />);
    const imgs = container.querySelectorAll("img.tile");
    expect(imgs.length).toBeGreaterThan(1);
    expect(imgs[0].getAttribute("src")).toBe("/api/sheets/s1/tiles/0/0/0.png");
    expect(imgs[0].getAttribute("alt")).toBe("");
    expect(imgs[0].getAttribute("draggable")).toBe("false");
  });
  it("renders only the level-0 backdrop when the page fits inside one tile on screen", () => {
    const { container } = render(<TileLayer sheet={D} view={{ scale: 0.4, tx: 0, ty: 0 }} size={{ w: 800, h: 534 }} />);
    const imgs = [...container.querySelectorAll("img.tile")];
    expect(imgs).toHaveLength(1);
    expect(imgs[0].getAttribute("src")).toBe("/api/sheets/s1/tiles/0/0/0.png");
  });
  it("sizes the layer to the paper, not to 1000 x 750", () => {
    const { container } = render(<TileLayer sheet={D} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    const layer = container.querySelector(".tilelayer");
    expect(layer.style.width).toBe("1000px");
    expect(layer.style.height).toBe("667px");
  });
  it("shows the sheet number and 'Drawing the sheet…' while pending, and the reason when failed", () => {
    render(<TileLayer sheet={{ ...D, renderStatus: "pending" }} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    expect(screen.getByText(/E2\.1/)).toBeInTheDocument();
    expect(screen.getByText("Drawing the sheet…")).toBeInTheDocument();
    render(<TileLayer sheet={{ ...D, renderStatus: "failed", renderError: "Couldn't draw this sheet. The takeoff still counts it." }} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    expect(screen.getByText("Couldn't draw this sheet. The takeoff still counts it.")).toBeInTheDocument();
  });
  it("requests no tile while pending or failed", () => {
    const { container } = render(<TileLayer sheet={{ ...D, renderStatus: "pending" }} view={{ scale: 1, tx: 0, ty: 0 }} size={{ w: 800, h: 600 }} />);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });
});
