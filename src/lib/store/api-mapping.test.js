/* ============================================================
   api-mapping.test.js — pure-function tests for the wire <-> store
   conversions in api-mapping.js. Starts with evidenceImageUrl
   (task-11-brief.md): the cache-busting evidence-image URL builder
   the item detail panel's evidence dialog depends on.
   ============================================================ */

import { describe, expect, test } from "vitest";
import { evidenceImageUrl, mapLaborRow, mapMaterialRow } from "./api-mapping.js";

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
});

describe("mapMaterialRow", () => {
  test("maps every field", () => {
    const row = { item_id: "abc", item_name: "x", quantity: "10", unit_price: "12.5",
                  source_label: "Company price", status: "ready", basis_note: "" };
    const mapped = mapMaterialRow(row);
    expect(mapped).toMatchObject({ itemId: "abc", unitPrice: 12.5, sourceLabel: "Company price" });
  });
});
