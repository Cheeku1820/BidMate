/* PlanWorkspace — modeled on NotesWorkspace.test.jsx: the layout's
   context is mocked, the screen fetches the plan itself. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import PlanWorkspace from "./PlanWorkspace.jsx";

const SCOPE = { id: "s1", kind: "excluded", text: "Site lighting.", editedText: null, status: "found", documentId: "d2", documentFilename: "E-set.pdf", page: 2, quote: "- Site lighting." };
const SPEC = { key: "spec:d1:260519", kind: "spec_section", text: "26 05 19 — Conductors", foundText: "26 05 19 — Conductors", editedText: null, status: "found",
  documentId: "d1", documentFilename: "Spec.pdf", page: null, quote: "SECTION 26 05 19", division: "26", sheetNumber: null, added: false, phaseId: null, places: [] };
const SCHED = { ...SPEC, key: "schedule:sheet:sh1", kind: "schedule", text: "Luminaire schedule", foundText: "Luminaire schedule", documentId: "d2", documentFilename: "E-set.pdf", page: 1, quote: "Luminaire schedule", division: null, sheetNumber: "E0.1" };
const PHASE = { ...SCHED, key: "phase:PHASE 1", kind: "phase", text: "Phase 1", foundText: "Phase 1", page: 3, quote: "Phase 1 power plan", sheetNumber: null,
  places: [{ documentId: "d2", documentFilename: "E-set.pdf", page: 3, quote: "Phase 1 power plan" }] };
const QUESTION = { key: "question:no_scale:sh2", status: "found", title: "No scale on E2.2", found: "E2.2 (Lighting plan) has no scale in its title block.",
  why: "Measured runs can't be given a length.", fix: "Set the scale on the blueprint.", where: "E2.2, title block.", documentId: "d2", documentFilename: "E-set.pdf", noteId: null };

const plan = (o = {}) => ({ readAt: "2026-09-21T10:00:00Z", reading: false, hasDrawings: true, undecided: 5,
  scope: [SCOPE], specs: [SPEC], schedules: [SCHED], phases: [PHASE], questions: [QUESTION], ...o });

const scanned = () => plan({ undecided: 1, scope: [], specs: [], schedules: [], phases: [], questions: [{ ...QUESTION, key: "question:scanned:d2",
  title: "Pages that could not be read", found: "12 of 12 pages in Gerber.pdf are scanned images with no readable text." }] });

function makeStore(p = plan()) {
  return {
    getPlan: vi.fn().mockResolvedValue(p),
    decidePlanLine: vi.fn().mockImplementation((_pid, key, change) => Promise.resolve({ ...[SPEC, SCHED, PHASE].find((l) => l.key === key), ...change, status: change.status ?? "found" })),
    decideScope: vi.fn().mockImplementation((id, change) => Promise.resolve({ ...SCOPE, ...change, status: change.status ?? "found" })),
    answerPlanQuestion: vi.fn().mockResolvedValue({ ...QUESTION, status: "answered", noteId: "n1" }),
    addPlanPhase: vi.fn().mockResolvedValue({ ...PHASE, key: "phase:added:ph1", text: "Phase 2", foundText: "Phase 2", added: true, phaseId: "ph1", documentId: null, documentFilename: null, page: null, quote: null, places: [] }),
    removePlanPhase: vi.fn().mockResolvedValue(null),
    startTakeoff: vi.fn().mockResolvedValue({ runId: "r1" }),
  };
}

let context;
vi.mock("../project/useWorkspaceContext.js", () => ({ useWorkspaceContext: () => context }));

function mount(store = makeStore()) {
  context = { store, projectId: "p1", project: { id: "p1", name: "Gerber" }, me: { id: "u1", name: "Dana" }, snapshot: { sheets: [], items: [] } };
  render(
    <MemoryRouter initialEntries={["/projects/p1/plan"]}>
      <Routes>
        <Route path="/projects/:projectId/plan" element={<PlanWorkspace />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
      </Routes>
    </MemoryRouter>,
  );
  return store;
}

afterEach(() => vi.clearAllMocks());

describe("PlanWorkspace", () => {
  it("renders the six sections, the undecided count, and no quantities", async () => {
    mount();
    expect(await screen.findByRole("heading", { name: "Scope stated in the documents" })).toBeInTheDocument();
    for (const name of ["Specification sections", "Schedules and legends", "Phasing", "Exclusions", "Open questions"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("5 lines not yet decided")).toBeInTheDocument();
    expect(screen.getByText("26 05 19 — Conductors")).toBeInTheDocument();
    expect(screen.getByText("Luminaire schedule")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No scale on E2.2" })).toBeInTheDocument();
    // Exclusions is a second view of the excluded scope line.
    expect(screen.getAllByText("Site lighting.")).toHaveLength(2);
    expect(screen.queryByText(/\bEA\b|\bLF\b|quantity/i)).toBeNull();
  });

  it("renders the scanned-set case as five empty sentences and one question", async () => {
    mount(makeStore(scanned()));
    expect(await screen.findByText("No scope statements were found in the documents.")).toBeInTheDocument();
    expect(screen.getByText("No specification sections were found in the uploaded documents.")).toBeInTheDocument();
    expect(screen.getByText("No schedule or legend sheet was found in the drawing set.")).toBeInTheDocument();
    expect(screen.getByText("The documents do not name any phase.")).toBeInTheDocument();
    expect(screen.getByText("The documents do not state anything as excluded or by others.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pages that could not be read" })).toBeInTheDocument();
    expect(screen.getByText("12 of 12 pages in Gerber.pdf are scanned images with no readable text.")).toBeInTheDocument();
  });

  it("starts the takeoff and goes to processing; a run in flight counts as started", async () => {
    const store = mount();
    await userEvent.click(await screen.findByRole("button", { name: "Start takeoff" }));
    expect(store.startTakeoff).toHaveBeenCalledWith("p1");
    expect(await screen.findByText("processing")).toBeInTheDocument();
  });

  it("disables Start takeoff while a drawing set is reading, with the help copy, and polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const store = makeStore(plan({ reading: true }));
    store.getPlan.mockResolvedValueOnce(plan({ reading: true })).mockResolvedValue(plan());
    mount(store);
    const button = await screen.findByRole("button", { name: "Start takeoff" });
    expect(button).toBeDisabled();
    expect(screen.getByText("A drawing set is still being read. Wait for it to finish before starting the takeoff.")).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(store.getPlan).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Start takeoff" })).toBeEnabled());
    vi.useRealTimers();
  });

  it("shows the server's refusal next to the button", async () => {
    const store = makeStore();
    store.startTakeoff.mockRejectedValue({ code: "drawings_still_reading", message: "A drawing set is still being read." });
    mount(store);
    await userEvent.click(await screen.findByRole("button", { name: "Start takeoff" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A drawing set is still being read.");
    expect(screen.queryByText("processing")).toBeNull();
  });

  // Every write is followed by a re-read (store.getPlan), so each of the
  // next four cases sets what that re-read answers before acting.
  it("a decision follows the server's answer and the undecided count drops", async () => {
    const store = mount();
    const specs = await screen.findByRole("region", { name: "Specification sections" });
    store.getPlan.mockResolvedValue(plan({ undecided: 4, specs: [{ ...SPEC, status: "confirmed" }] }));
    await userEvent.click(within(specs).getByRole("button", { name: "Confirm" }));
    expect(store.decidePlanLine).toHaveBeenCalledWith("p1", "spec:d1:260519", { status: "confirmed" });
    expect(await within(specs).findByText("Confirmed")).toBeInTheDocument();
    expect(screen.getByText("4 lines not yet decided")).toBeInTheDocument();
  });

  it("a scope decision made under Exclusions shows under Scope too", async () => {
    const store = mount();
    const exclusions = await screen.findByRole("region", { name: "Exclusions" });
    store.getPlan.mockResolvedValue(plan({ undecided: 4, scope: [{ ...SCOPE, status: "confirmed" }] }));
    await userEvent.click(within(exclusions).getByRole("button", { name: "Confirm" }));
    expect(store.decideScope).toHaveBeenCalledWith("s1", { status: "confirmed" });
    const scope = screen.getByRole("region", { name: "Scope stated in the documents" });
    expect(await within(scope).findByText("Confirmed")).toBeInTheDocument();
  });

  it("answers a question through the store and links to the note", async () => {
    const store = mount();
    store.getPlan.mockResolvedValue(plan({ undecided: 4, questions: [{ ...QUESTION, status: "answered", noteId: "n1" }] }));
    await userEvent.click(await screen.findByRole("button", { name: "Answer" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Your answer" }), "Use 1/8 inch.");
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(store.answerPlanQuestion).toHaveBeenCalledWith("p1", "question:no_scale:sh2", "Use 1/8 inch.");
    expect(await screen.findByRole("link", { name: "See the note" })).toHaveAttribute("href", "/projects/p1/notes");
  });

  it("adds and removes a phase through the store", async () => {
    const store = mount();
    const ADDED = { ...PHASE, key: "phase:added:ph1", text: "Phase 2", foundText: "Phase 2", added: true, phaseId: "ph1",
      documentId: null, documentFilename: null, page: null, quote: null, places: [] };
    store.getPlan.mockResolvedValue(plan({ phases: [PHASE, ADDED] }));
    await userEvent.type(await screen.findByRole("textbox", { name: "Phase name" }), "Phase 2");
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    expect(store.addPlanPhase).toHaveBeenCalledWith("p1", "Phase 2");
    expect(await screen.findByText("Stated by you")).toBeInTheDocument();
    store.getPlan.mockResolvedValue(plan());
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(store.removePlanPhase).toHaveBeenCalledWith("p1", "ph1");
    await waitFor(() => expect(screen.queryByText("Stated by you")).toBeNull());
  });

  it("says to upload documents when there are none", async () => {
    mount(makeStore(plan({ hasDrawings: false, readAt: null, undecided: 0, scope: [], specs: [], schedules: [], phases: [], questions: [] })));
    expect(await screen.findByRole("link", { name: "Upload documents to build the plan" })).toHaveAttribute("href", "/projects/p1/documents");
    expect(screen.getByRole("button", { name: "Start takeoff" })).toBeDisabled();
  });

  it("says so when the plan can't be loaded", async () => {
    const store = makeStore();
    store.getPlan.mockRejectedValue({ code: "network", message: "down" });
    mount(store);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load the plan. Check the connection and try again.");
  });
});
