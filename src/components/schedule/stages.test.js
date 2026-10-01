import { describe, expect, it } from "vitest";
import { STAGES, STAGE_LABELS, crewText, stageLabel } from "./stages.js";

describe("stages", () => {
  it("has the six stages in order, mirroring api/app/schedule/stages.py", () => {
    expect(STAGES).toEqual(["demolition", "rough_in", "wire_pull", "gear", "trim", "closeout"]);
    expect(STAGE_LABELS.rough_in).toBe("Rough-in");
    expect(stageLabel("closeout")).toBe("Close-out");
  });

  it("returns an unknown key rather than blanking it", () => {
    expect(stageLabel("painting")).toBe("painting");
  });

  it("labels a crew the way a bar does", () => {
    expect(crewText({ foreman: 1, journeyman: 2, apprentice: 2 })).toBe("1F 2J 2A");
    expect(crewText(undefined)).toBe("0F 0J 0A");
  });
});
