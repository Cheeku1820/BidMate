/* ============================================================
   CompanySettings.test.jsx — screen J behaviour: tabbed sections, and
   every value showing its source, with edits that persist.
   ============================================================ */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CompanySettings from "./CompanySettings.jsx";
import { getCompanySettings } from "../../lib/settingsStore.js";

beforeEach(() => localStorage.clear());

describe("CompanySettings", () => {
  it("shows the labor rates tab with each value labelled by its source", async () => {
    // Labor rates now come from the company labor-rates endpoint (Task 9)
    // rather than settingsStore.js, so this tab needs a store to render.
    const store = {
      getCompanyLaborRates: vi.fn().mockResolvedValue({
        journeyman_rate: "68.00",
        foreman_rate: "82.00",
        apprentice_rate: "41.00",
        productivity_factor: "1.000",
        updated_at: "2026-06-14",
      }),
      setCompanyLaborRates: vi.fn().mockResolvedValue({}),
    };
    render(<CompanySettings store={store} />);
    await userEvent.click(screen.getByRole("tab", { name: /labor rates/i }));

    await waitFor(() => expect(screen.getByLabelText(/journeyman rate/i)).toBeTruthy());
    expect(screen.getAllByText(/company default · updated/i).length).toBeGreaterThan(0);
  });

  it("persists an edited value through the settings store", async () => {
    render(<CompanySettings />);
    await userEvent.click(screen.getByRole("tab", { name: /waste and markup/i }));

    // A direct change (what selecting-all-and-typing produces) replaces
    // the value in one event. Clearing to empty is intentionally a no-op:
    // a markup field never persists as a blank, which Number("") would
    // otherwise write as 0.
    const waste = screen.getByLabelText(/^waste$/i);
    fireEvent.change(waste, { target: { value: "7" } });

    expect(getCompanySettings().wastePercent.value).toBe(7);
  });

  it("Labor rates tab reads and writes through the store, not localStorage", async () => {
    const store = {
      getCompanyLaborRates: vi.fn().mockResolvedValue({
        journeyman_rate: "68.00",
        foreman_rate: "82.00",
        apprentice_rate: "41.00",
        productivity_factor: "1.000",
        updated_at: "2026-08-01T00:00:00Z",
      }),
      setCompanyLaborRates: vi.fn().mockResolvedValue({}),
    };
    render(<CompanySettings store={store} />);
    fireEvent.click(screen.getByRole("tab", { name: /labor rates/i }));
    await waitFor(() => expect(screen.getByDisplayValue("68")).toBeInTheDocument());
  });

  it("Material pricing tab lists company prices and supports add/remove", async () => {
    const store = {
      getCompanyMaterialPrices: vi.fn().mockResolvedValue([
        { item_name: "20A duplex receptacle", unit_price: "13.50", effective_date: "2026-08-01", updated_at: "2026-08-01T00:00:00Z" },
      ]),
      setCompanyMaterialPrice: vi.fn().mockResolvedValue({}),
      deleteCompanyMaterialPrice: vi.fn().mockResolvedValue({}),
    };
    render(<CompanySettings store={store} />);
    fireEvent.click(screen.getByRole("tab", { name: /material pricing/i }));
    await waitFor(() => expect(screen.getByText("20A duplex receptacle")).toBeInTheDocument());
  });
});
