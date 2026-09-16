import { describe, expect, test } from "vitest";
import { saveStateText, timeOf } from "./format.js";

describe("saveStateText", () => {
  test("names the three autosave states and nothing for no state", () => {
    const at = Date.parse("2026-08-25T15:00:00Z");
    expect(saveStateText({ state: "saving", at })).toBe("Saving…");
    expect(saveStateText({ state: "error", at })).toBe("Couldn't save — retrying");
    expect(saveStateText({ state: "saved", at })).toBe("Saved " + timeOf(at));
    expect(saveStateText(null)).toBeNull();
  });
});
