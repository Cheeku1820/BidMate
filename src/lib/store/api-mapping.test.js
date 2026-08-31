/* ============================================================
   api-mapping.test.js — pure-function tests for the wire <-> store
   conversions in api-mapping.js. Starts with evidenceImageUrl
   (task-11-brief.md): the cache-busting evidence-image URL builder
   the item detail panel's evidence dialog depends on.
   ============================================================ */

import { describe, expect, test } from "vitest";
import { evidenceImageUrl } from "./api-mapping.js";

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
