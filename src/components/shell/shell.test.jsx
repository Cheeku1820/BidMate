/* ============================================================
   shell.test.jsx — AppShell, AppTopBar, and NotFound.

   Small components, but two of them encode rules that are easy to
   undo by accident:

   - AppTopBar's save state is where the "no save buttons anywhere"
     convention lives. If the region stops being a live region, the
     estimator loses the only signal that their work is being written.
   - NotFound's copy names a recovery action. Spec §20 forbids leaving a
     dead end, and this screen is the one an out-of-date link lands on.

   AppShell is thin, so it gets one structural assertion rather than a
   suite: the shell must render its navigation and whatever the route
   put in the outlet, because a regression there blanks every screen at
   once.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AppShell from "./AppShell.jsx";
import AppTopBar from "./AppTopBar.jsx";
import NotFound from "./NotFound.jsx";

describe("AppShell", () => {
  it("renders the company navigation around the routed screen", () => {
    render(
      <MemoryRouter initialEntries={["/projects"]}>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/projects" element={<p>Routed content</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("navigation", { name: /main/i })).toBeTruthy();
    expect(screen.getByText("Routed content")).toBeTruthy();
    // The outlet's content is inside the main landmark, not a sibling of
    // it -- otherwise "skip to content" and screen-reader landmark
    // navigation land in the wrong place.
    expect(screen.getByRole("main")).toContainElement(screen.getByText("Routed content"));
  });
});

describe("AppTopBar", () => {
  it("shows the title and, when given, the subtitle", () => {
    render(<AppTopBar title="Projects" subtitle="Riverside Medical Center" />);
    expect(screen.getByText("Projects")).toBeTruthy();
    expect(screen.getByText("Riverside Medical Center")).toBeTruthy();
  });

  it("omits the subtitle entirely rather than rendering an empty slot", () => {
    const { container } = render(<AppTopBar title="Projects" />);
    expect(container.querySelector(".app-top-bar-subtitle")).toBeNull();
  });

  it("announces save state politely, because there is no save button to look at", () => {
    // CLAUDE.md: everything autosaves and the save state lives in the top
    // bar. An estimator has no other confirmation that a change landed,
    // so this has to reach assistive technology without stealing focus.
    render(<AppTopBar title="Projects" saveState="Saved 2:41 PM" />);
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Saved 2:41 PM");
    expect(status).toHaveAttribute("aria-live", "polite");
  });

  it("renders no save-state region when there is nothing to report", () => {
    render(<AppTopBar title="Projects" />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("renders the workspace's own primary action", () => {
    render(<AppTopBar title="Projects" primaryAction={<button type="button">New project</button>} />);
    expect(screen.getByRole("button", { name: /new project/i })).toBeTruthy();
  });
});

describe("NotFound", () => {
  it("names a recovery action rather than leaving a dead end", () => {
    // Spec §20: error copy explains the user's recovery action, and
    // "Something went wrong" on its own is forbidden.
    render(
      <MemoryRouter>
        <NotFound />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: /isn't available/i })).toBeTruthy();
    expect(screen.getByRole("link", { name: /back to projects/i })).toHaveAttribute("href", "/projects");
  });
});
