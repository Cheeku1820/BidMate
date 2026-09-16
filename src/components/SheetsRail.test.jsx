import { describe, expect, it, test, vi } from "vitest";
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

  test("a sheet nothing was read from carries no kind badge", () => {
    // Its kind is "other" only because nothing decided it; the title
    // already says what the sheet is, and a "Sheet" badge beside
    // "Scanned sheet" is noise.
    rail([
      { ...base, id: "s1", number: "Page 12", title: "Scanned sheet", kind: "other",
        unreadableReason: "The sheet is a scanned image with no readable text, so it was not counted." },
      { ...base, id: "s2", number: "E0.0", title: "Cover", kind: "other" },
    ]);
    expect(screen.getByText("Scanned sheet")).toBeInTheDocument();
    expect(screen.getAllByText("Sheet", { selector: ".badge" })).toHaveLength(1);
  });

  test("the kind badge is not a status pill", () => {
    rail([{ ...base, id: "s1", number: "E0.1", title: "Legend", kind: "legend" }]);
    const badge = screen.getByText("Legend", { selector: ".badge" });
    expect(badge.className).not.toMatch(/pill|status|attention|approved|missing|ready/);
  });
});

it("shows the thumbnail once a sheet is rendered, and the dots before", () => {
  const sheets = [
    { id: "a", number: "E1", title: "t", renderStatus: "rendered", kind: "plan" },
    { id: "b", number: "E2", title: "t", renderStatus: "pending", kind: "plan" },
  ];
  const { container } = render(<SheetsRail sheets={sheets} items={[]} sheetId="a" onSelectSheet={() => {}} />);
  const img = container.querySelector('img[src="/api/sheets/a/thumb.png"]');
  expect(img).toBeTruthy(); expect(img.getAttribute("alt")).toBe("");
  expect(container.querySelectorAll(".sheetrow__thumb svg")).toHaveLength(1);
});
