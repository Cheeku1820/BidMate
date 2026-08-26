/* ============================================================
   ConfirmDrawings.test.jsx — screen D behaviour.

   The rules spec §5 puts weight on: an unresolved sheet (a missing
   scale) surfaces in a Needs attention section above the table, and
   unchecking every sheet disables Start takeoff (an empty set has
   nothing to take off).
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";

const renderConfirm = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/documents/confirm"]}>
      <Routes>
        <Route path="/projects/:projectId/documents/confirm" element={<ConfirmDrawings />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
      </Routes>
    </MemoryRouter>,
  );

describe("ConfirmDrawings", () => {
  it("surfaces a sheet with no scale as needing attention before takeoff", () => {
    renderConfirm();
    expect(screen.getByText(/needs attention before takeoff/i)).toBeTruthy();
    expect(screen.getByText(/no scale in its title block/i)).toBeTruthy();
  });

  it("disables Start takeoff once every sheet is excluded", async () => {
    renderConfirm();
    const start = screen.getAllByRole("button", { name: /start takeoff/i })[0];
    expect(start).toBeEnabled();

    for (const box of screen.getAllByRole("checkbox", { name: /include/i })) {
      await userEvent.click(box);
    }
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();
  });

  it("clears the attention notice when the unscaled sheet is excluded", async () => {
    renderConfirm();
    await userEvent.click(screen.getByRole("checkbox", { name: /include e2\.1/i }));
    expect(screen.queryByText(/needs attention before takeoff/i)).toBeNull();
  });
});
