import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import StageBars from "./StageBars.jsx";

function bar(stage, startWeek, endWeek, extra = {}) {
  return {
    stage, label: stage, hours: 40, crew: { foreman: 1, journeyman: 2, apprentice: 2 },
    productiveHoursPerDay: 6, durationDays: 2, start: null, end: null,
    startWeek, endWeek, sources: {}, neededCrew: null, overMax: false, overMaxNote: "", note: "",
    ...extra,
  };
}

const schedule = {
  relative: true,
  multiPhase: false,
  manpower: [],
  phases: [{
    id: "p1", name: "Phase 1",
    bars: [bar("demolition", 1, 1), bar("rough_in", 2, 2), bar("wire_pull", 2, 2), bar("gear", 2, 3)],
  }],
  leads: [],
};

describe("StageBars layout", () => {
  it("gives every stage its own row, so two in the same week cannot stack", () => {
    render(<StageBars schedule={schedule} selected={null} onSelect={() => {}} />);
    const rows = ["demolition", "rough_in", "wire_pull", "gear"].map(
      (stage) => screen.getByRole("button", { name: new RegExp(stage) }).style.gridRow,
    );
    expect(new Set(rows).size).toBe(4);
    // Rough-in and wire pull share week 2 but not a row.
    expect(rows[1]).not.toBe(rows[2]);
  });

  it("keeps the axis on the work when an order-by date falls far before it", () => {
    const withLead = {
      ...schedule,
      leads: [{
        itemId: "i1", itemName: "Switchboard MSB-1", phaseId: "p1", orderBy: "2026-05-29",
        orderByWeek: -38, passed: true, stale: false,
        note: "Order date has passed — 40 weeks lead, gear starts Mar 5",
      }],
    };
    render(<StageBars schedule={withLead} selected={null} onSelect={() => {}} />);
    // Week 1 through week 3 — not week -38 through week 3, which would
    // squeeze the whole job into the right-hand edge.
    expect(screen.getByText("Week 1")).toBeInTheDocument();
    expect(screen.queryByText("Week -38")).not.toBeInTheDocument();
    expect(screen.queryByText("Week 0")).not.toBeInTheDocument();
    // The marker is still there, clamped, and still says what happened.
    expect(screen.getByRole("img", { name: /Order by .*Switchboard MSB-1/ })).toBeInTheDocument();
    expect(screen.getByText(/Order date has passed/)).toBeInTheDocument();
  });
});
