import { describe, expect, it } from "vitest";
import { mapSchedule, mapSnapshot, mapStageCrew, mapStageSplit } from "./api-mapping.js";

const wire = {
  multi_phase: true,
  relative: false,
  peak_crew: 6,
  peak_week: 1,
  average_crew: "4.50",
  unscheduled_count: 2,
  unscheduled_note: "2 items aren't in the schedule yet — they need labor hours",
  default_split_count: 1,
  defaults_in_use: { splits: true, crews: false },
  expected_award_date: null,
  mobilization_date: "2026-10-05",
  manpower: [{ week: 1, start: "2026-10-05", foreman: 1, journeyman: 2, apprentice: 2 }],
  leads: [{
    item_id: "i1", item_name: "Switchboard MSB-1", item_status: "ready", phase_id: "p1", phase_name: "Phase 1",
    lead_weeks: null, source: null, source_label: "", quoted_at: null, needed_for_stage: "gear",
    needed_by: "2026-10-14", order_by: null, order_by_week: null, passed: false, stale: false, note: "", warning: null,
  }],
  phases: [{
    id: "p1", name: "Phase 1", sort_order: 0, start_date: null, required_finish_date: null, notes: "",
    sheet_ids: ["s1"], items_moved_in: 0, items_moved_out: 0,
    direct_hours: "100.00", general_conditions_hours: "7.00", material_total: "0.00",
    lines: [{ id: "l1", label: "Final and daily cleanup", hours: "3.00", source: "computed", percent_of_direct_hours: "3.00" }],
    bars: [{
      stage: "rough_in", label: "Rough-in", hours: "48.15",
      crew: { foreman: 1, journeyman: 2, apprentice: 2 },
      productive_hours_per_day: "6.00", duration_days: 2, start: "2026-10-05", end: "2026-10-06",
      start_week: 1, end_week: 1, sources: { hours: "computed", journeyman: "estimator" },
      needed_crew: null, over_max: false, over_max_note: "", note: "",
    }],
    start: "2026-10-05", end: "2026-10-14",
  }],
};

describe("mapSchedule", () => {
  it("camelCases, numbers the decimals, and leaves dates as ISO strings", () => {
    const schedule = mapSchedule(wire);
    expect(schedule.multiPhase).toBe(true);
    expect(schedule.averageCrew).toBe(4.5);
    expect(schedule.phases[0].bars[0].hours).toBe(48.15);
    expect(schedule.phases[0].bars[0].crew).toEqual({ foreman: 1, journeyman: 2, apprentice: 2 });
    expect(schedule.phases[0].bars[0].sources.journeyman).toBe("estimator");
    expect(schedule.phases[0].bars[0].start).toBe("2026-10-05");
    expect(schedule.phases[0].lines[0].percentOfDirectHours).toBe(3);
    expect(schedule.manpower[0].crew).toBe(5);
    expect(schedule.defaultsInUse).toEqual({ splits: true, crews: false });
  });

  it("keeps an unquoted lead time as null rather than inventing a number", () => {
    const lead = mapSchedule(wire).leads[0];
    expect(lead.leadWeeks).toBeNull();
    expect(lead.orderBy).toBeNull();
    expect(lead.sourceLabel).toBe("");
    expect(lead.neededBy).toBe("2026-10-14");
  });

  it("survives an empty schedule", () => {
    const empty = mapSchedule({ multi_phase: false, relative: true, average_crew: "0" });
    expect(empty.phases).toEqual([]);
    expect(empty.manpower).toEqual([]);
    expect(empty.leads).toEqual([]);
    expect(empty.peakCrew).toBe(0);
  });
});

describe("company table mappers", () => {
  it("maps a split row and a crew row", () => {
    expect(mapStageSplit({
      category_key: "devices", category_label: "Devices", demolition: "0", rough_in: "45",
      wire_pull: "25", gear: "0", trim: "25", closeout: "5", firm_edited: false,
    })).toEqual({
      categoryKey: "devices", categoryLabel: "Devices", demolition: 0, roughIn: 45,
      wirePull: 25, gear: 0, trim: 25, closeout: 5, firmEdited: false,
    });
    expect(mapStageCrew({
      stage: "rough_in", label: "Rough-in", foreman: 1, journeyman: 2, apprentice: 2,
      productive_hours_per_day: "6.00", productivity_factor: "1.000", max_crew: 6, firm_edited: true,
    }).productiveHoursPerDay).toBe(6);
  });
});

describe("phases on the snapshot", () => {
  it("carries the phase list the poll refreshes", () => {
    const snapshot = mapSnapshot({
      version: "v1",
      sheets: [],
      items: [],
      totals: { by_system: {}, approved_count: 0, remaining_count: 0, attention_count: 0, missing_count: 0, approved_units: "0" },
      undo: { can_undo: false, can_redo: false, undo_label: null, redo_label: null },
      presence: [],
      phases: [
        { id: "p1", name: "E sheets", sort_order: 0 },
        { id: "p2", name: "XE sheets", sort_order: 1 },
      ],
    });
    expect(snapshot.phases).toEqual([
      { id: "p1", name: "E sheets", sortOrder: 0 },
      { id: "p2", name: "XE sheets", sortOrder: 1 },
    ]);
  });

  it("reads an unphased project as an empty list rather than undefined", () => {
    const snapshot = mapSnapshot({
      version: "v1",
      sheets: [],
      items: [],
      totals: { by_system: {}, approved_count: 0, remaining_count: 0, attention_count: 0, missing_count: 0, approved_units: "0" },
      undo: { can_undo: false, can_redo: false, undo_label: null, redo_label: null },
      presence: [],
    });
    expect(snapshot.phases).toEqual([]);
  });
});
