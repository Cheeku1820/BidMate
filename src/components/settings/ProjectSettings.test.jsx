/* ============================================================
   ProjectSettings.test.jsx — screen K behaviour: project details, and
   the override chain with "Restore company default" on every override.
   ============================================================ */

import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectSettings from "./ProjectSettings.jsx";

const project = {
  id: "p1",
  name: "Cedar Ridge Warehouse",
  number: "26-0207",
  customer: "Bellweather Construction",
  location: "Stockton, CA",
  bidDueDate: null,
  revisionSetLabel: "E1.1 Rev 3",
  archivedAt: null,
};

const store = { listProjects: async () => [project] };

const renderSettings = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/settings"]}>
      <Routes>
        <Route path="/projects/:projectId/settings" element={<ProjectSettings store={store} />} />
        <Route path="/projects/:projectId/takeoff" element={<p>review</p>} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => localStorage.clear());

describe("ProjectSettings", () => {
  it("shows the project's own details", async () => {
    renderSettings();
    expect(await screen.findByText("Bellweather Construction")).toBeTruthy();
  });

  it("offers Restore company default only once a value is overridden, then restores it", async () => {
    renderSettings();
    const rate = await screen.findByLabelText(/journeyman rate/i);

    // No restore control while the value is the company default.
    expect(screen.queryByRole("button", { name: /restore company default/i })).toBeNull();

    await userEvent.type(rate, "{selectall}90");

    const restore = screen.getByRole("button", { name: /restore company default/i });
    expect(restore).toBeTruthy();
    // The overridden field is marked as an override, not by colour alone.
    const row = rate.closest(".settings-row");
    expect(within(row).getByText(/project override/i)).toBeTruthy();

    await userEvent.click(restore);
    expect(screen.queryByRole("button", { name: /restore company default/i })).toBeNull();
  });
});
