/* ============================================================
   NotesWorkspace.test.jsx — modeled on TakeoffSpreadsheet.test.jsx:
   useWorkspaceContext.js is mocked directly rather than rendered
   through the real ProjectWorkspaceLayout, since this screen is a
   plain child of it and the layout's own behavior is covered by
   ProjectWorkspaceLayout.test.jsx.

   Notes are not part of the review snapshot (Task 4's store methods
   are separate from getSnapshot()), so the mocked context here carries
   a `store` with the four note methods directly, the way the brief's
   "Consumes" line describes -- this screen calls them itself rather
   than reading notes off `snapshot`.
   ============================================================ */

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import NotesWorkspace from "./NotesWorkspace.jsx";

const NOTE = {
  id: "n1",
  projectId: "p1",
  scope: "project",
  scopeRef: null,
  title: "Existing panel LP-2 assumed reused",
  body: "Panel schedule shows LP-2 as existing to remain.",
  category: "existing_condition",
  status: "confirmed",
  rfiNeeded: false,
  usage: "reference",
  sourceRef: "",
  obsoleteAfterRevision: "",
  authorName: "Dana Whitfield",
  createdAt: "2026-08-28T10:00:00Z",
  updatedAt: "2026-08-28T10:00:00Z",
  appliedAt: null,
};

function makeStore({ notes = [] } = {}) {
  return {
    listNotes: vi.fn().mockResolvedValue(notes),
    createNote: vi.fn().mockResolvedValue({ ...NOTE, id: "new" }),
    updateNote: vi.fn().mockResolvedValue(NOTE),
    deleteNote: vi.fn().mockResolvedValue(undefined),
    startTakeoff: vi.fn().mockResolvedValue({ runId: "r1" }),
    getProcessing: vi.fn().mockResolvedValue(processing()),
  };
}

// What store.getProcessing reports once a re-run is going: the same
// shape screen E reads, so the same list renders here.
const processing = (over) => ({
  documents: [{ id: "d", filename: "E.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 2 }],
  run: {
    state: "running",
    reason: "",
    completeCount: 1,
    totalCount: 2,
    sheets: [
      { id: "s1", number: "E2.1", title: "Power plan", stage: "complete", reason: "", note: "", itemCount: 42 },
      { id: "s2", number: "E2.2", title: "Lighting plan", stage: "finding", reason: "", note: "", itemCount: 0 },
    ],
  },
  ...over,
});

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderNotes({ notes = [], store = makeStore({ notes }), sheets = [], project = { id: "p1", location: "Warehouse — Riverside, CA" } } = {}) {
  context = {
    store,
    projectId: "p1",
    project,
    me: { id: "u1", name: "Dana Whitfield" },
    // Fix round 1, finding 3: NoteForm's "which sheet" picker reads
    // sheets off the shared snapshot, the same place
    // TakeoffSpreadsheet.jsx reads them from.
    snapshot: { sheets, items: [] },
  };
  return render(
    <MemoryRouter>
      <NotesWorkspace />
    </MemoryRouter>,
  );
}

describe("NotesWorkspace", () => {
  it("summarises how many notes affect the estimate", async () => {
    renderNotes({
      notes: [
        { ...NOTE, id: "1", usage: "context" },
        { ...NOTE, id: "2", usage: "reference" },
        { ...NOTE, id: "3", usage: "context", rfiNeeded: true, status: "open" },
      ],
    });
    expect(await screen.findByText(/3 notes/)).toBeInTheDocument();
    expect(screen.getByText(/2 affect this estimate/)).toBeInTheDocument();
    expect(screen.getByText(/1 open RFI/)).toBeInTheDocument();
  });

  it("shows what each note does to the estimate, in words", async () => {
    renderNotes({ notes: [{ ...NOTE, usage: "context" }] });
    expect(await screen.findByText("Used in this estimate")).toBeInTheDocument();
  });

  it("does not count a company-scoped note as affecting the estimate unless it feeds the takeoff", async () => {
    // Fix round 1, finding 1: scope alone used to be enough to read as
    // "Company standard" and be counted in "N affect this estimate",
    // even with "Feeds the takeoff" left off -- disagreeing with the
    // apply banner, which correctly ignored it (keyed on usage alone).
    renderNotes({ notes: [{ ...NOTE, scope: "company", usage: "reference" }] });
    expect(await screen.findByText(/^1 note/)).toBeInTheDocument();
    expect(screen.queryByText(/affect this estimate/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply notes and re-run/i })).not.toBeInTheDocument();
    expect(screen.getByText("Reference only")).toBeInTheDocument();
  });

  it("filters to one scope", async () => {
    renderNotes({
      notes: [
        { ...NOTE, id: "1", title: "Company rule note", scope: "company" },
        { ...NOTE, id: "2", title: "Project note", scope: "project" },
      ],
    });
    await userEvent.click(await screen.findByRole("button", { name: /company standard/i }));
    expect(screen.getByText("Company rule note")).toBeInTheDocument();
    expect(screen.queryByText("Project note")).not.toBeInTheDocument();
  });

  it("creates a note through the form, not only through a panel", async () => {
    const store = makeStore({ notes: [] });
    renderNotes({ store });
    await userEvent.click(await screen.findByRole("button", { name: /add note/i }));
    // Scoped to the open dialog: the dialog itself carries an
    // accessible name of "Add note" (Modal.jsx's aria-label={title}),
    // which getByLabelText's aria-label fallback strategy would
    // otherwise also match for a bare /note/i query -- within(dialog)
    // searches descendants only, so the dialog element itself drops out
    // and the one remaining match is the actual field.
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText(/title/i), "Existing panel LP-2 reused");
    await userEvent.type(within(dialog).getByLabelText(/note/i), "Panel schedule shows LP-2 as existing.");
    await userEvent.click(within(dialog).getByLabelText(/feeds the takeoff/i));
    await userEvent.click(within(dialog).getByRole("button", { name: /save note/i }));
    await waitFor(() => expect(store.createNote).toHaveBeenCalled());
    expect(store.createNote.mock.calls[0][1].usage).toBe("context");
  });

  it("offers to apply notes that no re-run has carried in yet", async () => {
    renderNotes({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
    expect(await screen.findByRole("button", { name: /apply notes and re-run/i })).toBeInTheDocument();
  });

  it("does not offer to apply when every context note is already applied", async () => {
    renderNotes({ notes: [{ ...NOTE, usage: "context", appliedAt: "2026-08-28T10:00:00Z" }] });
    expect(await screen.findByText(/6 notes|1 note/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply notes and re-run/i })).not.toBeInTheDocument();
  });

  it("shows an empty state that names the next action", async () => {
    renderNotes({ notes: [] });
    expect(await screen.findByRole("button", { name: /add note/i })).toBeInTheDocument();
  });

  it("deletes a note once the estimator confirms", async () => {
    const store = makeStore({ notes: [NOTE] });
    renderNotes({ store, notes: [NOTE] });
    await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^delete note$/i }));
    await waitFor(() => expect(store.deleteNote).toHaveBeenCalledWith(NOTE.id));
  });

  it("keeps the note and shows the error when delete fails, rather than closing on an assumption", async () => {
    // Fix round 1, finding 2: handleDeleteConfirmed had no catch --  a
    // rejected promise left the dialog open with no message and the
    // note untouched, with nothing telling the estimator it hadn't
    // worked. Deletion isn't undoable, so this is the one flow that
    // can least afford ambiguity.
    const store = makeStore({ notes: [NOTE] });
    store.deleteNote = vi.fn().mockRejectedValue({
      code: "conflict",
      message: "This note was already removed by another reviewer.",
    });
    renderNotes({ store, notes: [NOTE] });
    await userEvent.click(await screen.findByRole("button", { name: /^delete$/i }));
    await userEvent.click(await screen.findByRole("button", { name: /^delete note$/i }));

    expect(await screen.findByText(/already removed by another reviewer/i)).toBeInTheDocument();
    // The dialog is still open (its own "Delete note" button is still
    // there) and the note is still in the list underneath it.
    expect(screen.getByRole("button", { name: /^delete note$/i })).toBeInTheDocument();
    expect(screen.getByText(NOTE.title)).toBeInTheDocument();
  });

  it("does not offer takeoff item as a scope until a picker exists for it", async () => {
    renderNotes({ notes: [] });
    await userEvent.click(await screen.findByRole("button", { name: /add note/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("option", { name: /takeoff item/i })).not.toBeInTheDocument();
  });

  it("requires choosing which sheet before a sheet-scoped note can be saved", async () => {
    // Fix round 1, finding 3: "Sheet" scope used to offer no way to say
    // which sheet, so the note was permanently unanchored.
    const store = makeStore({ notes: [] });
    const sheets = [{ id: "s1", number: "E1.1", title: "Level 1 power" }];
    renderNotes({ store, sheets });
    await userEvent.click(await screen.findByRole("button", { name: /add note/i }));
    const dialog = screen.getByRole("dialog");

    await userEvent.type(within(dialog).getByLabelText(/title/i), "Panel LP-2 note");
    await userEvent.type(within(dialog).getByLabelText(/note/i), "Panel schedule shows LP-2 as existing.");
    await userEvent.selectOptions(within(dialog).getByLabelText(/applies to/i), "sheet");
    await userEvent.click(within(dialog).getByRole("button", { name: /save note/i }));

    expect(store.createNote).not.toHaveBeenCalled();
    expect(within(dialog).getByText(/choose which sheet/i)).toBeInTheDocument();

    await userEvent.selectOptions(within(dialog).getByLabelText(/which sheet/i), "s1");
    await userEvent.click(within(dialog).getByRole("button", { name: /save note/i }));

    await waitFor(() => expect(store.createNote).toHaveBeenCalled());
    expect(store.createNote.mock.calls[0][1].scopeRef).toBe("s1");
  });

  describe("applying notes and re-running", () => {
    // The re-run is the same queued run screen E watches: this screen
    // starts it (store.startTakeoff) and then shows the same per-sheet
    // list, polling store.getProcessing until the run finishes.
    afterEach(() => {
      vi.useRealTimers();
    });

    it("starts a run, says sheets keep processing, and shows the same sheet list as screen E", async () => {
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(store.startTakeoff).toHaveBeenCalledWith("p1");
      expect(
        await screen.findByText("Re-run started. Sheets keep processing and are reviewable as they finish."),
      ).toBeInTheDocument();
      expect(await screen.findByText("Finding electrical items")).toBeInTheDocument();
      expect(screen.getByText("Complete")).toBeInTheDocument();
      expect(screen.getByText("1 of 2 sheets complete")).toBeInTheDocument();
      expect(store.getProcessing).toHaveBeenCalledWith("p1");
      // No reclassified count is claimed: the run is still going.
      expect(screen.queryByText(/reclassified/i)).not.toBeInTheDocument();
    });

    it("polls every 3 seconds until the run finishes, then stops", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      store.getProcessing = vi
        .fn()
        .mockResolvedValueOnce(processing())
        .mockResolvedValue(processing({ run: { ...processing().run, state: "complete", completeCount: 2 } }));
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(await screen.findByText("Finding electrical items")).toBeInTheDocument();
      await act(() => vi.advanceTimersByTimeAsync(3100));
      expect(screen.getByText("2 of 2 sheets complete")).toBeInTheDocument();
      // Finished: the "started" line gives way to the list's final state.
      expect(screen.queryByText(/re-run started/i)).not.toBeInTheDocument();
      const calls = store.getProcessing.mock.calls.length;
      await act(() => vi.advanceTimersByTimeAsync(6200));
      expect(store.getProcessing).toHaveBeenCalledTimes(calls);
    });

    it("says a takeoff is already running when the re-run is refused, and does not claim a start", async () => {
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      store.startTakeoff = vi.fn().mockRejectedValue({ code: "run_in_flight", message: "already running" });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(
        await screen.findByText("A takeoff is already running. Apply the notes again once it finishes."),
      ).toBeInTheDocument();
      expect(screen.queryByText(/re-run started/i)).not.toBeInTheDocument();
      expect(store.getProcessing).not.toHaveBeenCalled();
    });

    it("reports a failed re-run with a recovery action, and shows no sheet list", async () => {
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      store.startTakeoff = vi.fn().mockRejectedValue({ code: "no_readable_drawings", message: "None of the uploaded documents could be read." });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(await screen.findByText(/none of the uploaded documents could be read/i)).toBeInTheDocument();
      expect(store.getProcessing).not.toHaveBeenCalled();
      expect(screen.queryByText(/re-run started/i)).not.toBeInTheDocument();
    });
  });
});
