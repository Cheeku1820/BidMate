/* ============================================================
   CompanySettings.test.jsx — screen J behaviour: tabbed sections, and
   every value showing its source, with edits that persist.
   ============================================================ */

import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CompanySettings from "./CompanySettings.jsx";
import { getCompanySettings } from "../../lib/settingsStore.js";

beforeEach(() => localStorage.clear());

describe("CompanySettings", () => {
  it("shows the labor rates tab with each value labelled by its source", async () => {
    render(<CompanySettings />);
    await userEvent.click(screen.getByRole("tab", { name: /labor rates/i }));

    expect(screen.getByLabelText(/journeyman rate/i)).toBeTruthy();
    expect(screen.getAllByText(/company default · updated/i).length).toBeGreaterThan(0);
  });

  it("persists an edited value through the settings store", async () => {
    render(<CompanySettings />);
    await userEvent.click(screen.getByRole("tab", { name: /waste and markup/i }));

    const waste = screen.getByLabelText(/^waste$/i);
    await userEvent.clear(waste);
    await userEvent.type(waste, "7");

    expect(getCompanySettings().wastePercent.value).toBe(7);
  });
});
