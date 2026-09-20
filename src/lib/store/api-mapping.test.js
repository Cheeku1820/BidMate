/* ============================================================
   api-mapping.test.js — pure-function tests for the wire <-> store
   conversions in api-mapping.js. Starts with evidenceImageUrl
   (task-11-brief.md): the cache-busting evidence-image URL builder
   the item detail panel's evidence dialog depends on.
   ============================================================ */

import { describe, expect, test } from "vitest";
import { evidenceImageUrl, mapItem, mapLaborRow, mapMaterialRow, mapSheet } from "./api-mapping.js";

describe("evidenceImageUrl", () => {
  test("returns a URL when the item has an image", () => {
    const item = { id: "abc-123", version: 4, evidence: { has_image: true } };
    expect(evidenceImageUrl(item)).toBe("/api/items/abc-123/evidence-image?v=4");
  });

  test("returns null when the item has no image", () => {
    const item = { id: "abc-123", version: 4, evidence: { has_image: false } };
    expect(evidenceImageUrl(item)).toBeNull();
  });

  test("returns null when the item has no evidence at all", () => {
    const item = { id: "abc-123", version: 4, evidence: null };
    expect(evidenceImageUrl(item)).toBeNull();
  });
});

describe("mapLaborRow", () => {
  test("maps every field from snake_case to camelCase", () => {
    const row = {
      item_id: "abc", item_name: "20A duplex receptacle", quantity: "10",
      hours_per_unit: "0.5", hours_source_label: "Estimated basis",
      rate: "78", rate_source_label: "Estimated basis",
      adjusted_hours: "5.5", labor_cost: "429", status: "ready", basis_note: "Rate based on Sacramento, CA.",
    };
    const mapped = mapLaborRow(row);
    expect(mapped).toMatchObject({
      itemId: "abc", itemName: "20A duplex receptacle", hoursPerUnit: 0.5,
      hoursSourceLabel: "Estimated basis", rate: 78, status: "ready",
    });
  });

  test("handles null hours/rate without throwing", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null,
                  hours_source_label: null, rate: null, rate_source_label: null,
                  adjusted_hours: null, labor_cost: null, status: "missing", basis_note: "" };
    expect(() => mapLaborRow(row)).not.toThrow();
    expect(mapLaborRow(row).hoursPerUnit).toBeNull();
  });

  test("carries the adjustment percent and reason, and defaults them when absent", () => {
    const withAdjustment = mapLaborRow({
      item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null, hours_source_label: null,
      rate: null, rate_source_label: null, adjusted_hours: null, labor_cost: null, status: "missing",
      basis_note: "", adjustment_percent: "25.00", adjustment_reason: "Mounting height above 16 ft",
    });
    expect(withAdjustment.adjustmentPercent).toBe(25);
    expect(withAdjustment.adjustmentReason).toBe("Mounting height above 16 ft");

    const without = mapLaborRow({
      item_id: "abc", item_name: "x", quantity: "1", hours_per_unit: null, hours_source_label: null,
      rate: null, rate_source_label: null, adjusted_hours: null, labor_cost: null, status: "missing", basis_note: "",
    });
    expect(without.adjustmentPercent).toBeNull();
    expect(without.adjustmentReason).toBe("");
  });
});

describe("mapMaterialRow", () => {
  test("maps every field", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "10", unit_price: "12.5",
                  source_label: "Company price", status: "ready", basis_note: "" };
    const mapped = mapMaterialRow(row);
    expect(mapped).toMatchObject({ itemId: "abc", unitPrice: 12.5, sourceLabel: "Company price" });
  });

  test("maps the raw source and reason for an allowance row", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "10", unit_price: "15.5",
                  source: "allowance", source_label: "Allowance", reason: "no vendor quote yet",
                  status: "approved", basis_note: "" };
    const mapped = mapMaterialRow(row);
    expect(mapped).toMatchObject({ source: "allowance", reason: "no vendor quote yet" });
  });

  test("source and reason default to null and empty string when absent", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "10", unit_price: null,
                  source_label: null, status: "missing", basis_note: "" };
    const mapped = mapMaterialRow(row);
    expect(mapped).toMatchObject({ source: null, reason: "" });
  });
});

describe("mapSheet", () => {
  test("carries kind and defaults it to plan", () => {
    expect(mapSheet({ id: "x", number: "E1", title: "t", kind: "diagram" }).kind).toBe("diagram");
    expect(mapSheet({ id: "x", number: "E1", title: "t" }).kind).toBe("plan");
  });

  test("carries the render fields, never render_key", () => {
    const mapped = mapSheet({
      id: "x", number: "E1", title: "t", render_status: "rendered", render_error: "", max_zoom: 3,
    });
    expect(mapped).toMatchObject({ renderStatus: "rendered", renderError: "", maxZoom: 3 });
    expect(mapped.renderKey).toBeUndefined();
  });

  test("defaults the render fields when the wire omits them", () => {
    const mapped = mapSheet({ id: "x", number: "E1", title: "t" });
    expect(mapped).toMatchObject({ renderStatus: "pending", renderError: "", maxZoom: null });
  });
});


describe("mapItem", () => {
  test("carries rejectReason and resolveNote, null when absent", () => {
    const base = { id: "i1", sheet_id: "s1", name: "x", symbol: "receptacle", system: "Power", category: "Devices",
      quantity: "1", unit: "ea", status: "ready", notes: "", warnings: [], version: 1 };
    expect(mapItem({ ...base, reject_reason: "not a device", resolve_note: null })).toMatchObject({ rejectReason: "not a device", resolveNote: null });
    expect(mapItem(base)).toMatchObject({ rejectReason: null, resolveNote: null });
  });
});
