import { describe, expect, it } from "vitest";
import { COLUMNS, applicableColumns } from "./spreadsheetColumns.js";

const phases = [{ id: "p1", name: "Phase 1" }, { id: "p2", name: "XE sheets" }];

describe("the Phase column", () => {
  it("does not exist on a single-phase project", () => {
    expect(applicableColumns({ phases: [] }).map((c) => c.key)).not.toContain("phase");
    expect(applicableColumns({ phases: [phases[0]] }).map((c) => c.key)).not.toContain("phase");
  });

  it("appears once a second phase exists, naming the item's resolved phase", () => {
    const ctx = { phases, phasesById: Object.fromEntries(phases.map((p) => [p.id, p])) };
    const columns = applicableColumns(ctx);
    expect(columns.map((c) => c.key)).toContain("phase");
    const column = COLUMNS.find((c) => c.key === "phase");
    expect(column.render({ phaseId: "p2" }, ctx)).toBe("XE sheets");
  });

  it("shows a dash rather than a blank when an item has no phase yet", () => {
    const ctx = { phases, phasesById: {} };
    expect(COLUMNS.find((c) => c.key === "phase").render({ phaseId: null }, ctx)).toBe("—");
  });
});
