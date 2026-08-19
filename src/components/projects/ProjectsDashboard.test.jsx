import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ProjectsDashboard from "./ProjectsDashboard.jsx";

const projects = [
  {
    id: "p1",
    name: "Riverside Medical Center - Bldg C",
    number: "26-0418",
    customer: "Hensel Phelps",
    location: "Sacramento, CA",
    bidDueDate: "2026-09-14",
    stage: "review",
    archivedAt: null,
    updatedAt: "2026-08-17T18:00:00Z",
    estimatorName: "Dana Whitfield",
    itemsTotal: 412,
    itemsApproved: 103,
    warningsOpen: 6,
    missingInfo: 2,
  },
  {
    id: "p2",
    name: "Oakview High School",
    number: "26-0501",
    customer: "Swinerton",
    location: "Modesto, CA",
    bidDueDate: null,
    stage: "setup",
    archivedAt: null,
    updatedAt: "2026-08-16T09:00:00Z",
    estimatorName: null,
    itemsTotal: 0,
    itemsApproved: 0,
    warningsOpen: 0,
    missingInfo: 0,
  },
];

const store = { listProjects: async () => projects };

const renderDashboard = () =>
  render(
    <MemoryRouter>
      <ProjectsDashboard store={store} me={{ id: "u1", name: "Dana Whitfield" }} />
    </MemoryRouter>,
  );

describe("ProjectsDashboard", () => {
  it("renders every spec §5.1 column for each project", async () => {
    renderDashboard();
    await screen.findByText("Riverside Medical Center - Bldg C");

    for (const header of [
      /project/i, /customer/i, /location/i, /bid due/i,
      /estimator/i, /stage/i, /progress/i, /warnings/i, /updated/i,
    ]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeTruthy();
    }

    expect(screen.getByText("Hensel Phelps")).toBeTruthy();
    expect(screen.getByText("26-0418")).toBeTruthy();
  });

  it("shows an unassigned estimator and an absent bid date as blanks with meaning", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");
    // Never a fabricated date and never the literal string "null".
    expect(screen.queryByText("null")).toBeNull();
    expect(screen.getAllByText("Not set").length).toBeGreaterThan(0);
  });

  it("does not render progress as a percentage alone", async () => {
    // Status is never colour alone and a bare bar is not a label: the
    // count has to be readable as text (CLAUDE.md).
    renderDashboard();
    expect(await screen.findByText("103 of 412 approved")).toBeTruthy();
  });

  it("filters to projects needing review", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.click(screen.getByRole("button", { name: /needs review/i }));

    expect(screen.getByText("Riverside Medical Center - Bldg C")).toBeTruthy();
    expect(screen.queryByText("Oakview High School")).toBeNull();
  });

  it("searches across name, number, and customer", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.type(screen.getByLabelText(/search projects/i), "Swinerton");

    expect(screen.getByText("Oakview High School")).toBeTruthy();
    expect(screen.queryByText("Riverside Medical Center - Bldg C")).toBeNull();
  });

  it("names the recovery action when no project matches", async () => {
    renderDashboard();
    await screen.findByText("Oakview High School");

    await userEvent.type(screen.getByLabelText(/search projects/i), "zzzz");

    expect(screen.getByText(/no projects match/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /clear search/i })).toBeTruthy();
  });

  it("shows an empty state with a create action when there are no projects", async () => {
    render(
      <MemoryRouter>
        <ProjectsDashboard store={{ listProjects: async () => [] }} me={{ id: "u1" }} />
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: /new project/i })).toBeTruthy();
  });

  it("names a recovery action and retries without a full page reload when the list fails to load", async () => {
    let calls = 0;
    const flaky = {
      listProjects: async () => {
        calls += 1;
        if (calls === 1) throw new Error("network unreachable");
        return projects;
      },
    };
    render(
      <MemoryRouter>
        <ProjectsDashboard store={flaky} me={{ id: "u1" }} />
      </MemoryRouter>,
    );

    const retry = await screen.findByRole("button", { name: /try again/i });
    expect(screen.getByText(/network unreachable/i)).toBeTruthy();

    await userEvent.click(retry);

    await screen.findByText("Riverside Medical Center - Bldg C");
    expect(calls).toBe(2);
  });
});
