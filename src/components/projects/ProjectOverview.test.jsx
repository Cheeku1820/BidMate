// Pin a timezone behind UTC before anything else in this file runs, same
// as ProjectsDashboard.test.jsx -- bidDueDate is a date-only ISO string
// ("2026-09-14") and this catches the UTC-midnight-parses-a-day-early bug
// if it's ever reintroduced here.
process.env.TZ = "America/Denver";

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectOverview from "./ProjectOverview.jsx";

const project = {
  id: "p1",
  name: "Riverside Medical Center - Bldg C",
  number: "26-0418",
  customer: "Hensel Phelps",
  location: "Sacramento, CA",
  bidDueDate: "2026-09-14",
  stage: "review",
  revisionSetLabel: "E2.1 Rev 2",
  archivedAt: null,
  updatedAt: "2026-08-17T18:00:00Z",
  estimatorName: "Dana Whitfield",
  itemsTotal: 412,
  itemsApproved: 103,
  warningsOpen: 6,
  missingInfo: 2,
};

const renderOverview = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1"]}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectOverview store={store} me={{ id: "u1" }} />} />
      </Routes>
    </MemoryRouter>,
  );

describe("ProjectOverview", () => {
  it("shows the project details, progress, and unresolved warnings", async () => {
    renderOverview({ listProjects: async () => [project] });

    expect(await screen.findByRole("heading", { name: /riverside medical center/i })).toBeTruthy();
    expect(screen.getByText("Hensel Phelps")).toBeTruthy();
    expect(screen.getByText("103 of 412 approved")).toBeTruthy();
    expect(screen.getByText(/2 items are missing required information/i)).toBeTruthy();
  });

  it("renders the bid due date as the same calendar date in every timezone", async () => {
    // Regression coverage for the UTC-midnight-parsing bug the brief's
    // own formatDate reintroduced -- this file must import the same
    // UTC-anchored formatter ProjectsDashboard.jsx uses, not a second
    // copy that formats in the local zone.
    renderOverview({ listProjects: async () => [project] });
    expect(await screen.findByText("Sep 14, 2026")).toBeTruthy();
    expect(screen.queryByText("Sep 13, 2026")).toBeNull();
  });

  it("offers a continue action into the review workspace", async () => {
    renderOverview({ listProjects: async () => [project] });
    const link = await screen.findByRole("link", { name: /continue review/i });
    expect(link.getAttribute("href")).toBe("/projects/p1/takeoff");
  });

  it("shows an unassigned estimator and an absent bid date as blanks with meaning", async () => {
    const bare = { ...project, estimatorName: null, bidDueDate: null };
    renderOverview({ listProjects: async () => [bare] });
    await screen.findByRole("heading", { name: /riverside medical center/i });
    expect(screen.queryByText("null")).toBeNull();
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
  });

  it("names a recovery action when the project isn't found", async () => {
    renderOverview({ listProjects: async () => [] });
    expect(await screen.findByRole("link", { name: /back to projects/i })).toBeTruthy();
    // The "not found" copy must not also be shown for a load failure --
    // see the dedicated error-state test below.
    expect(screen.queryByText(/network unreachable/i)).toBeNull();
  });

  it("names what actually happened and offers a retry when the project fails to load, distinct from a missing project", async () => {
    // Review finding 2: a listProjects() network failure and a genuinely
    // absent project must not render the same "may have been archived"
    // copy -- that copy is simply false when nothing was archived and the
    // request just failed. This mirrors ProjectsDashboard.test.jsx's own
    // "names a recovery action ... when the list fails to load" case.
    let calls = 0;
    const flaky = {
      listProjects: async () => {
        calls += 1;
        if (calls === 1) throw new Error("network unreachable");
        return [project];
      },
    };
    renderOverview(flaky);

    const retry = await screen.findByRole("button", { name: /try again/i });
    expect(screen.getByText(/network unreachable/i)).toBeTruthy();
    expect(screen.queryByText(/may have been archived/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /back to projects/i })).toBeNull();

    await userEvent.click(retry);

    expect(await screen.findByRole("heading", { name: /riverside medical center/i })).toBeTruthy();
    expect(calls).toBe(2);
  });

  it("does not offer to continue review when the project has no items yet", async () => {
    // Review finding 1(a): a project with itemsTotal === 0 has no
    // takeoff to continue. "Continue review" is the screen's primary
    // action and the single most likely thing to click right after
    // creating a project -- offering it here would follow through to a
    // workspace showing a different project's items, which is a
    // fabricated quantity presented as this project's evidence.
    const empty = { ...project, itemsTotal: 0, itemsApproved: 0, warningsOpen: 0, missingInfo: 0 };
    renderOverview({ listProjects: async () => [empty] });

    await screen.findByRole("heading", { name: /riverside medical center/i });
    expect(screen.queryByRole("link", { name: /continue review/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /open the blueprint takeoff/i })).toBeNull();
    expect(screen.getByText(/upload isn't built yet/i)).toBeTruthy();
  });
});
