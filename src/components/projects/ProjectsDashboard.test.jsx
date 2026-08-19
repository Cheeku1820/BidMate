// Pin a timezone behind UTC before anything else in this file runs.
// "2026-09-14" (a date-only, no-time ISO string) parses as UTC
// midnight per the ECMAScript spec; in any zone behind UTC — every US
// timezone — formatting that instant with no `timeZone` override
// renders it a day early. America/Denver makes that regression visible
// here: without the fix, the assertion below sees "Sep 13, 2026".
process.env.TZ = "America/Denver";

import { StrictMode } from "react";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
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

  it("renders a date-only bid due date as the same calendar date in every timezone", async () => {
    // Regression coverage for the UTC-midnight-parsing bug: this file
    // runs under TZ=America/Denver (set above), a zone behind UTC. A
    // formatter that does `new Date("2026-09-14").toLocaleDateString()`
    // with no `timeZone` override renders "Sep 13, 2026" here — a day
    // early. Asserting the correct date, and that the wrong one is
    // absent, is what makes this test fail honestly if that regresses.
    renderDashboard();
    expect(await screen.findByText("Sep 14, 2026")).toBeTruthy();
    expect(screen.queryByText("Sep 13, 2026")).toBeNull();
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

describe("ProjectsDashboard sorting", () => {
  // Three rows, all visible under the default "Active" filter: two with
  // distinct bid dates plus one with none, so the null-handling branch
  // in compare() is actually exercised rather than merely present.
  const sortProjects = [
    {
      id: "s1",
      name: "Zephyr Logistics Hub",
      number: "26-0700",
      customer: "Acme Builders",
      location: "Fresno, CA",
      bidDueDate: "2026-09-20",
      stage: "review",
      archivedAt: null,
      updatedAt: "2026-08-01T00:00:00Z",
      estimatorName: null,
      itemsTotal: 0,
      itemsApproved: 0,
      warningsOpen: 0,
      missingInfo: 0,
    },
    {
      id: "s2",
      name: "Anchor Point Clinic",
      number: "26-0701",
      customer: "Acme Builders",
      location: "Fresno, CA",
      bidDueDate: "2026-09-05",
      stage: "review",
      archivedAt: null,
      updatedAt: "2026-08-02T00:00:00Z",
      estimatorName: null,
      itemsTotal: 0,
      itemsApproved: 0,
      warningsOpen: 0,
      missingInfo: 0,
    },
    {
      id: "s3",
      name: "Midtown Office Tower",
      number: "26-0702",
      customer: "Acme Builders",
      location: "Fresno, CA",
      bidDueDate: null,
      stage: "review",
      archivedAt: null,
      updatedAt: "2026-08-03T00:00:00Z",
      estimatorName: null,
      itemsTotal: 0,
      itemsApproved: 0,
      warningsOpen: 0,
      missingInfo: 0,
    },
  ];

  const sortStore = { listProjects: async () => sortProjects };

  const renderForSort = () =>
    render(
      <MemoryRouter>
        <ProjectsDashboard store={sortStore} me={{ id: "u1" }} />
      </MemoryRouter>,
    );

  function rowOrder() {
    return screen
      .getAllByRole("rowheader")
      .map((cell) => within(cell).getByRole("link").textContent);
  }

  it("sorts by bid due date with unset dates last, not first", async () => {
    renderForSort();
    await screen.findByText("Zephyr Logistics Hub");

    await userEvent.selectOptions(screen.getByLabelText(/sort by/i), "bidDate");

    expect(rowOrder()).toEqual([
      "Anchor Point Clinic", // 2026-09-05
      "Zephyr Logistics Hub", // 2026-09-20
      "Midtown Office Tower", // no bid date — last, not first
    ]);
  });

  it("sorts alphabetically by project name", async () => {
    renderForSort();
    await screen.findByText("Zephyr Logistics Hub");

    await userEvent.selectOptions(screen.getByLabelText(/sort by/i), "name");

    expect(rowOrder()).toEqual([
      "Anchor Point Clinic",
      "Midtown Office Tower",
      "Zephyr Logistics Hub",
    ]);
  });
});

describe("ProjectsDashboard under StrictMode", () => {
  // src/main.jsx renders the whole app inside <React.StrictMode>, which
  // in development double-invokes every mount effect synchronously
  // (run, cleanup, run again) before any pending promise settles. A
  // mounted-ness guard that only sets itself back to true when first
  // created -- rather than re-arming at the top of the effect body on
  // every invocation -- gets permanently tripped by that cleanup, and
  // listProjects()'s later resolution is silently dropped: the
  // dashboard hangs on "Loading projects..." forever. None of the
  // other tests in this file catch this, because none of them render
  // under StrictMode -- this is the one that has to.
  it("still loads project rows after StrictMode's simulated double-mount", async () => {
    render(
      <StrictMode>
        <MemoryRouter>
          <ProjectsDashboard store={store} me={{ id: "u1" }} />
        </MemoryRouter>
      </StrictMode>,
    );

    expect(await screen.findByText("Riverside Medical Center - Bldg C")).toBeTruthy();
    expect(screen.queryByText("Loading projects…")).toBeNull();
  });
});
