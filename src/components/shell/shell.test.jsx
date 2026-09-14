/* ============================================================
   shell.test.jsx — AppShell, AppTopBar, and NotFound.

   Small components, but two of them encode rules that are easy to
   undo by accident:

   - AppTopBar's save state is where the "no save buttons anywhere"
     convention lives. If the region stops being a live region, the
     estimator loses the only signal that their work is being written.
   - NotFound's copy names a recovery action. Spec §20 forbids leaving a
     dead end, and this screen is the one an out-of-date link lands on.

   AppShell is no longer thin. It now decides which of the two rails a
   route gets -- the company nav outside a project, the project sidebar
   inside one -- and gets a suite for it, because that decision is the
   only thing standing between an estimator and losing the project
   navigation on the screens they spend the most time in. The structural
   assertion it always had stays too: a regression there blanks every
   screen at once.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import AppShell from "./AppShell.jsx";
import AppTopBar from "./AppTopBar.jsx";
import NotFound from "./NotFound.jsx";

const renderShell = (path, { store = null } = {}) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell store={store} />}>
          <Route path="*" element={<p>Routed content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );

describe("AppShell", () => {
  it("renders the company navigation around the routed screen", () => {
    renderShell("/projects");

    expect(screen.getByRole("navigation", { name: /main/i })).toBeTruthy();
    expect(screen.getByText("Routed content")).toBeTruthy();
    // The outlet's content is inside the main landmark, not a sibling of
    // it -- otherwise "skip to content" and screen-reader landmark
    // navigation land in the wrong place.
    expect(screen.getByRole("main")).toContainElement(screen.getByText("Routed content"));
  });

  it("swaps the company nav for the project rail inside a project", () => {
    // One rail, never two: stacking them costs ~250px on the takeoff
    // canvas, the screen spec §12 says must stay the largest element.
    renderShell("/projects/p1/documents");

    expect(screen.getByRole("navigation", { name: /project workspaces/i })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: /main/i })).toBeNull();
  });

  it("carries the rail into the review workspaces, which used to have none", () => {
    for (const path of ["/projects/p1/takeoff", "/projects/p1/spreadsheet", "/projects/p1/export"]) {
      const view = renderShell(path);
      expect(screen.getByRole("navigation", { name: /project workspaces/i })).toBeTruthy();
      view.unmount();
    }
  });

  it("treats /projects/new as company level, not as a project called new", () => {
    // It belongs to no project yet; a project rail here would link every
    // workspace to an id that does not exist.
    renderShell("/projects/new");
    expect(screen.getByRole("navigation", { name: /main/i })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: /project workspaces/i })).toBeNull();
  });

  it("starts the rail collapsed on the takeoff route and expanded elsewhere", () => {
    const view = renderShell("/projects/p1/takeoff");
    expect(screen.getByRole("button", { name: /expand navigation/i })).toBeTruthy();
    view.unmount();

    renderShell("/projects/p1/documents");
    expect(screen.getByRole("button", { name: /collapse navigation/i })).toBeTruthy();
  });

  it("loads the project row for the rail's header card", async () => {
    const store = {
      listProjects: async () => [{ id: "p1", name: "Riverside Medical Center", itemsTotal: 0, itemsApproved: 0 }],
    };
    renderShell("/projects/p1/documents", { store });

    await waitFor(() => expect(screen.getByText("Riverside Medical Center")).toBeTruthy());
  });

  it("renders the rail without a card when the store cannot list projects", async () => {
    // Every unit test with a minimal store mock takes this path, and so
    // does a listProjects() that fails. A rail with no card is the right
    // degraded state; a crash is not.
    const store = { listProjects: async () => { throw new Error("offline"); } };
    const { container } = renderShell("/projects/p1/documents", { store });

    await waitFor(() => expect(screen.getByRole("navigation", { name: /project workspaces/i })).toBeTruthy());
    expect(container.querySelector(".project-card")).toBeNull();
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

  it("renders a breadcrumb back to company level when one is given", () => {
    // The project sidebar replaces the company nav inside a project, so
    // this trail is a project screen's only route back out.
    render(
      <MemoryRouter>
        <AppTopBar title="Documents" breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]} />
      </MemoryRouter>,
    );

    const crumbs = screen.getByRole("navigation", { name: /breadcrumb/i });
    expect(within(crumbs).getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/projects");
    // The current page is named but not a link to itself.
    expect(within(crumbs).queryByRole("link", { name: "Documents" })).toBeNull();
  });

  it("renders no breadcrumb region when a screen gives none", () => {
    const { container } = render(<AppTopBar title="Projects" />);
    expect(container.querySelector(".app-top-bar-crumbs")).toBeNull();
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
