import { describe, expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SheetsRail from "./SheetsRail.jsx";

const base = { discipline: "Electrical", revision: "A", scale: "", plan: "", superseded: false };

function rail(sheets) {
  return render(
    <SheetsRail sheets={sheets} items={[]} sheetId={null} onSelectSheet={vi.fn()}
      filter="all" onFilter={vi.fn()} query="" onQuery={vi.fn()} open onToggleOpen={vi.fn()} />
  );
}

describe("SheetsRail sheet kind", () => {
  test("a schedule sheet is labelled, a plan is not", () => {
    rail([
      { ...base, id: "s1", number: "E0.3", title: "Panel schedules", kind: "schedule" },
      { ...base, id: "s2", number: "E2.1", title: "First floor plan", kind: "plan" },
    ]);
    expect(screen.getByText("Schedule")).toBeInTheDocument();
    expect(screen.queryByText("Electrical plan")).not.toBeInTheDocument();
  });

  test("the kind badge is not a status pill", () => {
    rail([{ ...base, id: "s1", number: "E0.1", title: "Legend", kind: "legend" }]);
    const badge = screen.getByText("Legend", { selector: ".badge" });
    expect(badge.className).not.toMatch(/pill|status|attention|approved|missing|ready/);
  });
});
