import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScheduleWorkspace from "./ScheduleWorkspace.jsx";

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => context }));

function bar(stage, extra = {}) {
  return {
    stage,
    label: stage === "rough_in" ? "Rough-in" : stage,
    hours: 36,
    crew: { foreman: 1, journeyman: 2, apprentice: 2 },
    productiveHoursPerDay: 6,
    durationDays: 2,
    start: null,
    end: null,
    startWeek: 1,
    endWeek: 1,
    sources: { hours: "computed" },
    neededCrew: null,
    overMax: false,
    overMaxNote: "",
    note: "",
    ...extra,
  };
}

function phase(extra = {}) {
  return {
    id: "p1",
    name: "Phase 1",
    sortOrder: 0,
    startDate: null,
    requiredFinishDate: null,
    notes: "",
    sheetIds: ["s1"],
    itemsMovedIn: 0,
    itemsMovedOut: 0,
    directHours: 0,
    generalConditionsHours: 0,
    materialTotal: 0,
    lines: [],
    bars: [],
    start: null,
    end: null,
    ...extra,
  };
}

function schedule(extra = {}) {
  return {
    multiPhase: false,
    relative: true,
    phases: [phase()],
    manpower: [],
    peakCrew: 0,
    peakWeek: 0,
    averageCrew: 0,
    leads: [],
    unscheduledCount: 0,
    unscheduledNote: "",
    defaultSplitCount: 0,
    defaultsInUse: { splits: true, crews: true },
    expectedAwardDate: null,
    mobilizationDate: null,
    ...extra,
  };
}

function setup(body = schedule()) {
  const store = {
    getSchedule: vi.fn().mockResolvedValue(body),
    createPhase: vi.fn().mockResolvedValue(schedule({ multiPhase: true })),
    proposePhases: vi.fn().mockResolvedValue({ phases: [], note: "No phasing found in the sheet numbers." }),
  };
  context = {
    store,
    projectId: "proj",
    snapshot: { sheets: [{ id: "s1", number: "E-1.0", title: "Power plan" }], items: [] },
    saved: { state: "saved", at: 0 },
    runMutation: (fn) => fn(),
    showToast: vi.fn(),
  };
  return store;
}

function renderScreen() {
  return render(
    <MemoryRouter>
      <ScheduleWorkspace />
    </MemoryRouter>,
  );
}

describe("ScheduleWorkspace", () => {
  beforeEach(() => {
    context = null;
  });

  it("sends the estimator to Labor when nothing has hours yet", async () => {
    setup();
    renderScreen();
    expect(await screen.findByText("Nothing to schedule yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Labor" })[0]).toHaveAttribute("href", "/projects/proj/labor");
  });

  it("hides every phase affordance until a second phase exists", async () => {
    setup(schedule({ phases: [phase({ bars: [bar("rough_in")] })] }));
    renderScreen();
    // The name shows twice by design: once as the phase row's heading
    // and once as the bar grid's row label.
    await screen.findByRole("button", { name: "Phase 1" });
    expect(screen.queryByRole("button", { name: /Move Phase 1 up/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove phase/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Assign sheets")).not.toBeInTheDocument();
  });

  it("adds a phase through the store and reports it in the estimator's words", async () => {
    const store = setup();
    renderScreen();
    await screen.findByText("Phase 1");
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    await userEvent.type(screen.getByLabelText("Phase name"), "Phase 2{enter}");
    await waitFor(() =>
      expect(store.createPhase).toHaveBeenCalledWith("proj", { name: "Phase 2", afterPhaseId: "p1" }),
    );
    expect(context.showToast).toHaveBeenCalledWith("Added Phase 2");
  });

  it("says weeks are relative when nothing carries a date", async () => {
    setup(schedule({ phases: [phase({ bars: [bar("rough_in")] })] }));
    renderScreen();
    expect(await screen.findByText(/Weeks are relative/)).toBeInTheDocument();
  });

  it("names the firm's default split as a default, never a recommendation", async () => {
    setup(schedule({ phases: [phase({ bars: [bar("rough_in")] })], defaultSplitCount: 3 }));
    renderScreen();
    expect(await screen.findByText("Default split — set yours in Company settings")).toBeInTheDocument();
    expect(screen.getByText("3 items use the default split")).toBeInTheDocument();
  });

  it("opens the bar editor with the values the API computed", async () => {
    setup(schedule({ phases: [phase({ bars: [bar("rough_in", { sources: { hours: "computed", journeyman: "estimator" } })] })] }));
    renderScreen();
    const barButton = await screen.findByRole("button", { name: /Rough-in — 36 h, 1F 2J 2A, 2 days/ });
    expect(barButton).toHaveTextContent("Yours");
    await userEvent.click(barButton);
    expect(await screen.findByLabelText("Journeyman")).toHaveValue("2");
    expect(screen.getByRole("button", { name: "Reset journeyman to computed" })).toBeInTheDocument();
  });

  it("shows a flagged item with no quote as not yet quoted, and draws no date", async () => {
    setup(schedule({
      leads: [{
        itemId: "i1", itemName: "Switchboard MSB-1", itemStatus: "ready", phaseId: "p1", phaseName: "Phase 1",
        leadWeeks: null, source: null, sourceLabel: "", quotedAt: null, neededForStage: "gear",
        neededBy: "2027-02-22", orderBy: null, orderByWeek: null, passed: false, stale: false, note: "", warning: null,
      }],
    }));
    renderScreen();
    expect(await screen.findByText("Not yet quoted")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "—" })).toBeInTheDocument();
  });
});
