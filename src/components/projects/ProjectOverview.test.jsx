// Pin a timezone behind UTC before anything else in this file runs, same
// as ProjectsDashboard.test.jsx -- bidDueDate is a date-only ISO string
// ("2026-09-14") and this catches the UTC-midnight-parses-a-day-early bug
// if it's ever reintroduced here.
process.env.TZ = "America/Denver";

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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
  });
});
