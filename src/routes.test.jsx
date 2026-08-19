/* ============================================================
   routes.test.jsx — the route table resolves, and the shell renders
   around it. Not a rendering-detail test: the point is that adding a
   fourteenth workspace later is a row in one table rather than a change
   in four files.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes } from "react-router-dom";
import { appRoutes } from "./routes.jsx";

const store = {
  me: async () => ({ id: "u1", name: "Dana Whitfield" }),
  listProjects: async () => [],
  subscribe: () => () => {},
};

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>{appRoutes({ store, me: { id: "u1", name: "Dana Whitfield" }, onSignedOut: () => {} })}</Routes>
    </MemoryRouter>,
  );
}

describe("appRoutes", () => {
  it("renders the company navigation on a company-level route", async () => {
    renderAt("/projects");
    expect(await screen.findByRole("navigation", { name: /main/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /projects/i })).toBeTruthy();
  });

  it("redirects the root path to the projects dashboard", async () => {
    renderAt("/");
    expect(await screen.findByRole("heading", { name: /projects/i })).toBeTruthy();
  });

  it("shows a recovery path rather than a blank screen for an unknown route", async () => {
    // Spec §20: error copy names the user's recovery action. "Something
    // went wrong" alone is explicitly disallowed.
    renderAt("/projects/does-not-exist/nowhere");
    expect(await screen.findByRole("link", { name: /back to projects/i })).toBeTruthy();
  });
});
