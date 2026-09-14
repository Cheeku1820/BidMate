/* ============================================================
   EstimateDemo.test.jsx — the Basis card's product language.

   This screen renders whatever the estimate service returns, including
   which pricing source produced the number. It shipped that as
   "Automated (Claude)", which puts a model name in front of an
   estimator — CLAUDE.md's first product rule, and the one most easily
   broken by a single ternary. The estimator's question is what the
   number rests on, not which vendor computed it.

   The service is mocked at `fetch`: this component talks straight to
   the estimate service rather than through the store, so there is no
   store seam to mock instead.
   ============================================================ */

import { describe, expect, test, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import EstimateDemo from "./EstimateDemo.jsx";

const PAYLOAD = {
  location: "Unalaska, AK",
  location_note: "Rate based on Unalaska, AK area cost data.",
  wiring_note:
    "Branch wiring is estimated at 30 feet per device. Conduit and wire quantities follow that rule " +
    "rather than a measured route, so check them against the job before the total is relied on.",
  labor_rate: 110,
  material_factor: 1.45,
  source: "llm",
  sheets: [{ number: "E2.1", page: 1, unreadable: null }],
  items: [
    {
      name: "20A duplex receptacle", system: "Power", category: "Devices", unit: "ea",
      quantity: 10, status: "ready", sheet: "E2.1", material_cost: 595.4,
      labor_hours: 12.6, labor_cost: 1386, total_cost: 1981.4, sheets: ["E2.1"],
    },
  ],
  totals: {
    material: 595.4, labor_hours: 12.6, labor_cost: 1386,
    total_direct_cost: 1981.4, item_count: 1, attention_count: 0,
  },
};

async function renderResult(payload) {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
  const { container } = render(
    <MemoryRouter>
      <EstimateDemo />
    </MemoryRouter>,
  );
  const input = container.querySelector('input[type="file"]');
  const file = new File(["%PDF-1.4"], "drawings.pdf", { type: "application/pdf" });
  fireEvent.change(input, { target: { files: [file] } });
  fireEvent.click(screen.getByRole("button", { name: "Estimate" }));
  await waitFor(() => expect(screen.getByText("Basis")).toBeInTheDocument());
  return container;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("EstimateDemo basis card", () => {
  test("names no model when the estimate came from the automated path", async () => {
    const container = await renderResult(PAYLOAD);
    const rendered = container.textContent;

    // The specific regression: a vendor name in estimator-facing copy.
    for (const banned of ["Claude", "Anthropic", "GPT", "LLM", "model"]) {
      expect(rendered).not.toMatch(new RegExp(`\\b${banned}\\b`, "i"));
    }
    // Nor a confidence figure, the other half of the same rule.
    expect(rendered).not.toMatch(/\bconfidence\b/i);
    expect(rendered).not.toMatch(/\d+\s*%/);
  });

  test("says what the number rests on, in the vocabulary the pricing screens use", async () => {
    await renderResult(PAYLOAD);
    expect(screen.getByText("Estimated basis")).toBeInTheDocument();
  });

  test("still distinguishes the regional table from the estimated basis", async () => {
    await renderResult({ ...PAYLOAD, source: "deterministic" });
    expect(screen.getByText("Regional table")).toBeInTheDocument();
    expect(screen.queryByText("Estimated basis")).not.toBeInTheDocument();
  });

  test("discloses the wiring assumption beside the location basis", async () => {
    await renderResult(PAYLOAD);
    expect(screen.getByText(/Rate based on Unalaska, AK area cost data\./)).toBeInTheDocument();
    expect(screen.getByText(/Branch wiring is estimated at 30 feet per device\./)).toBeInTheDocument();
  });

  test("renders no wiring note when the engine sent none", async () => {
    await renderResult({ ...PAYLOAD, wiring_note: "" });
    expect(screen.queryByText(/Branch wiring is estimated/)).not.toBeInTheDocument();
  });
});
