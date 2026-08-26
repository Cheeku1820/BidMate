/* ============================================================
   projectStage.test.js — the dashboard's derived values.

   These live in a module rather than inside the table component because
   the same numbers appear on the project overview (spec §6.2) and would
   otherwise be computed twice and drift. Same reasoning as ROADMAP.md
   invariant 1 applied one level down.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { STAGES, matchesFilter, reviewProgress, stageLabel } from "./projectStage.js";

const project = (over = {}) => ({
  stage: "review",
  archivedAt: null,
  itemsTotal: 12,
  itemsApproved: 3,
  warningsOpen: 2,
  missingInfo: 1,
  ...over,
});

describe("reviewProgress", () => {
  it("reports approved out of total with a rounded percentage", () => {
    expect(reviewProgress(project())).toEqual({ approved: 3, total: 12, percent: 25 });
  });

  it("reports zero rather than NaN for an empty project", () => {
    // A project created but not yet processed has no items. Dividing by
    // zero here renders "NaN%" in a table column, which reads as a bug to
    // an estimator and is one.
    expect(reviewProgress(project({ itemsTotal: 0, itemsApproved: 0 }))).toEqual({
      approved: 0,
      total: 0,
      percent: 0,
    });
  });
});

describe("stageLabel", () => {
  it("returns sentence-case labels for every stage", () => {
    for (const stage of STAGES) {
      expect(stageLabel(stage.key)).toBe(stage.label);
      expect(stage.label[0]).toBe(stage.label[0].toUpperCase());
      expect(stage.label.slice(1)).toBe(stage.label.slice(1).toLowerCase());
    }
  });

  it("falls back to the raw key rather than throwing on an unknown stage", () => {
    // A stage added server-side before the client knows about it must not
    // blank the column.
    expect(stageLabel("negotiation")).toBe("negotiation");
  });
});

describe("matchesFilter", () => {
  it("excludes archived projects from every filter except archived", () => {
    const archived = project({ archivedAt: "2026-07-01T00:00:00Z" });
    expect(matchesFilter(archived, "active")).toBe(false);
    expect(matchesFilter(archived, "needsReview")).toBe(false);
    expect(matchesFilter(archived, "archived")).toBe(true);
  });

  it("treats needsReview as any unapproved work, not just the review stage", () => {
    expect(matchesFilter(project({ stage: "review" }), "needsReview")).toBe(true);
    expect(
      matchesFilter(project({ stage: "pricing", itemsApproved: 12, itemsTotal: 12 }), "needsReview"),
    ).toBe(false);
  });

  it("holds readyToExport back while any missing information remains", () => {
    // Missing information blocks completion with no override (CLAUDE.md).
    // A dashboard that says "ready to export" over a blocking item is
    // telling the estimator something the finish-review dialog will
    // immediately contradict.
    const blocked = project({ stage: "export", itemsApproved: 11, itemsTotal: 12, missingInfo: 1 });
    expect(matchesFilter(blocked, "readyToExport")).toBe(false);

    const clear = project({ stage: "export", itemsApproved: 12, itemsTotal: 12, missingInfo: 0 });
    expect(matchesFilter(clear, "readyToExport")).toBe(true);
  });

  it("does not count zero-item projects as needing review or ready to export", () => {
    // A freshly created project with no processed items must not report as
    // ready to export. Without the `total > 0` guard in fullyApproved, the
    // test `0 === 0` evaluates true, and with missingInfo: 0 the project
    // would appear ready to export on the dashboard—a project not yet
    // processed, sitting under "Ready to export." The guard exists to
    // prevent this silent, misleading failure.
    const unprocessed = project({ itemsTotal: 0, itemsApproved: 0, missingInfo: 0 });
    expect(matchesFilter(unprocessed, "needsReview")).toBe(false);
    expect(matchesFilter(unprocessed, "readyToExport")).toBe(false);
  });
});
