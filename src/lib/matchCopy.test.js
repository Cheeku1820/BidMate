import { describe, expect, it } from "vitest";
import * as copy from "./matchCopy.js";

describe("match copy", () => {
  it("reads as an instrument", () => {
    for (const s of [copy.DRAW_PROMPT, copy.SEARCHING, copy.found(3), copy.NONE_FOUND, copy.NOT_SURE, copy.addLabel(3)]) {
      expect(s).not.toMatch(/!|please|successfully|\bAI\b|%/);
      expect(s[0]).toBe(s[0].toUpperCase());
    }
  });
  it("counts", () => {
    expect(copy.found(3)).toBe("3 matches found");
    expect(copy.found(1)).toBe("1 match found");
    expect(copy.addLabel(14)).toBe("Add 14 to the takeoff");
  });
});
