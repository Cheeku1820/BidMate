import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EstimateSummary from "./EstimateSummary.jsx";

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => context }));

function line(extra = {}) {
  return {
    id: null,
    title: "Power",
    origin: "counted",
    basis: null,
    basisLabel: null,
    where: "Takeoff spreadsheet",
    found: "2 counted lines.",
    why: null,
    value: "2",
    unit: "lines",
    amount: 450,
    source: null,
    ...extra,
  };
}

function section(key, label, extra = {}) {
  return { key, label, countedCount: 1, assumedCount: 0, subtotal: null, lines: [line()], ...extra };
}

function estimate(extra = {}) {
  return {
    projectName: "Kittle's Saxony",
    revisionSetLabel: "E1.1 Rev 3",
    sheetCount: 11,
    directCost: 486200,
    range: { low: 413000, high: 559000, spread: 73000 },
    countedCount: 61,
    assumedCount: 23,
    unpricedCount: 0,
    excludedValue: 0,
    sections: [
      section("scope", "Scope", {
        assumedCount: 1,
        lines: [
          line({ title: "Division 26 power, lighting and devices", amount: null, value: null, unit: null }),
          line({
            title: "Temporary power excluded",
            origin: "assumed",
            basis: "standard_exclusion",
            basisLabel: "Standard exclusion",
            found: "No document addressed temporary power.",
            amount: null,
            value: null,
            unit: null,
            source: "engine",
          }),
        ],
      }),
      section("takeoff", "Takeoff quantities"),
      section("labor", "Labor", { subtotal: 211400 }),
      section("material", "Material", { subtotal: 274800 }),
    ],
    qualifications: [
      {
        title: "Temporary power excluded",
        found: "No document addressed temporary power.",
        why: "It is commonly the general contractor's.",
        where: "Scope documents were read for temporary power language.",
        basisLabel: "Standard exclusion",
        excludedValue: null,
      },
    ],
    emptyReason: null,
    ...extra,
  };
}

beforeEach(() => {
  context = {
    projectId: "p1",
    store: { getEstimate: vi.fn().mockResolvedValue(estimate()) },
  };
});

describe("EstimateSummary", () => {
  it("renders four sections in spec order", async () => {
    render(<EstimateSummary />);
    const headings = await screen.findAllByRole("heading", { level: 2 });
    const labels = headings.map((h) => h.textContent.replace(/^\d+\s*/, ""));
    expect(labels.slice(0, 4)).toEqual(["Scope", "Takeoff quantities", "Labor", "Material"]);
  });

  it("tags each line with a word, not colour alone", async () => {
    render(<EstimateSummary />);
    expect(await screen.findAllByText("Assumed")).not.toHaveLength(0);
    expect(screen.getAllByText("Counted")).not.toHaveLength(0);
  });

  it("shows the qualifications block built from the assumed lines", async () => {
    render(<EstimateSummary />);
    expect(await screen.findByText(/what this number assumes/i)).toBeInTheDocument();
  });

  it("never renders a review-status label", async () => {
    render(<EstimateSummary />);
    await screen.findByText(/what this number assumes/i);
    for (const label of ["Ready to review", "Needs attention", "Missing information", "Estimator approved"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("says on its face that it is not a bid", async () => {
    render(<EstimateSummary />);
    expect(await screen.findByText(/not a bid/i)).toBeInTheDocument();
  });

  it("offers no approval control", async () => {
    render(<EstimateSummary />);
    await screen.findByText(/what this number assumes/i);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("prints the number and the budget range", async () => {
    render(<EstimateSummary />);
    expect(await screen.findByText("$486,200")).toBeInTheDocument();
    expect(screen.getByText(/\$413,000 – \$559,000/)).toBeInTheDocument();
  });

  it("collapses the range onto the number when nothing was assumed", async () => {
    context.store.getEstimate = vi.fn().mockResolvedValue(
      estimate({ assumedCount: 0, range: { low: 486200, high: 486200, spread: 0 } }),
    );
    render(<EstimateSummary />);
    expect(await screen.findByText(/every line was read from the documents/i)).toBeInTheDocument();
    expect(screen.queryByText(/budget range/i)).not.toBeInTheDocument();
  });

  it("states the reason when the project is empty", async () => {
    context.store.getEstimate = vi.fn().mockResolvedValue(
      estimate({
        directCost: 0,
        sections: [],
        qualifications: [],
        emptyReason: "No documents have been processed for this project yet, so there is nothing to estimate.",
      }),
    );
    render(<EstimateSummary />);
    expect(await screen.findByText(/nothing to estimate/i)).toBeInTheDocument();
    expect(screen.queryByText("$0")).not.toBeInTheDocument();
  });

  it("renders an unpriced line blank, not as zero", async () => {
    context.store.getEstimate = vi.fn().mockResolvedValue(
      estimate({
        sections: [
          section("material", "Material", {
            lines: [line({ title: "Unclassified symbol", amount: null, value: null, unit: null })],
          }),
        ],
      }),
    );
    render(<EstimateSummary />);
    const row = (await screen.findByText("Unclassified symbol")).closest("tr");
    expect(within(row).queryByText("$0")).not.toBeInTheDocument();
    expect(within(row).getByText(/not priced/i)).toBeInTheDocument();
  });

  it("distinguishes a line priced at zero from one nothing priced", async () => {
    context.store.getEstimate = vi.fn().mockResolvedValue(
      estimate({
        sections: [
          section("material", "Material", {
            lines: [line({ title: "Fire alarm rough-in by others", amount: 0, value: null, unit: null })],
          }),
        ],
      }),
    );
    render(<EstimateSummary />);
    const row = (await screen.findByText("Fire alarm rough-in by others")).closest("tr");
    expect(within(row).getByText("$0")).toBeInTheDocument();
    expect(within(row).queryByText(/not priced/i)).not.toBeInTheDocument();
  });

  it("shows an exclusion as money removed, not as a cost", async () => {
    context.store.getEstimate = vi.fn().mockResolvedValue(
      estimate({
        excludedValue: 48900,
        sections: [
          section("scope", "Scope", {
            lines: [
              line({
                title: "Fire alarm by others",
                origin: "assumed",
                basis: "standard_exclusion",
                basisLabel: "Standard exclusion",
                amount: 48900,
                value: null,
                unit: null,
              }),
            ],
          }),
        ],
      }),
    );
    render(<EstimateSummary />);
    const row = (await screen.findByText("Fire alarm by others")).closest("tr");
    expect(within(row).getByText("−$48,900")).toBeInTheDocument();
  });

  it("marks assumed rows for a reader who cannot see the colour", async () => {
    render(<EstimateSummary />);
    const row = (await screen.findByText("Temporary power excluded")).closest("tr");
    expect(row.className).toContain("est-assumed");
    expect(within(row).getByText("Assumed")).toBeInTheDocument();
  });

  it("names the basis on every assumed line", async () => {
    render(<EstimateSummary />);
    await screen.findByText("Temporary power excluded");
    expect(screen.getAllByText(/Standard exclusion/).length).toBeGreaterThan(0);
  });

  it("shows a section subtotal where there is one", async () => {
    render(<EstimateSummary />);
    expect(await screen.findByText("$211,400")).toBeInTheDocument();
    expect(screen.getByText("$274,800")).toBeInTheDocument();
  });

  it("names a recovery action when the estimate cannot be loaded", async () => {
    context.store.getEstimate = vi.fn().mockRejectedValue(new Error("Network error"));
    render(<EstimateSummary />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
