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

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import NotesWorkspace from "./NotesWorkspace.jsx";
import { setUploadedFiles, clearUploadedFiles } from "../../lib/uploadedFiles.js";
import * as engineClient from "../../lib/engineClient.js";

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
    reprocess: vi.fn().mockResolvedValue({ reclassified: 0, preserved: 0, added: 0, removed: 0 }),
  };
}

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
    // A re-run needs the engine's payload for the same drawings the
    // project was first processed from -- getUploadedFiles(projectId) is
    // how the client still has them, in memory, for this session. These
    // two tests exercise the happy and unhappy paths for what happens
    // once that payload exists and store.reprocess is reached; the
    // "no files in memory" state (the common one, since ProcessingStatus
    // clears this map right after the first successful process) gets its
    // own test below.
    beforeEach(() => {
      setUploadedFiles("p1", [{ file: new File([new Uint8Array(1)], "e1.1.pdf", { type: "application/pdf" }), docType: "Drawings" }]);
      vi.spyOn(engineClient, "estimateProject").mockResolvedValue({ sheets: [], items: [] });
    });

    afterEach(() => {
      clearUploadedFiles("p1");
      vi.restoreAllMocks();
    });

    it("says how many approved items a re-run left alone", async () => {
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      store.reprocess = vi.fn().mockResolvedValue({ reclassified: 7, preserved: 3, added: 0, removed: 0 });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(await screen.findByText(/3 approved items were left unchanged/i)).toBeInTheDocument();
      expect(screen.getByText(/7 items reclassified/i)).toBeInTheDocument();
    });

    it("reports a failed re-run with a recovery action", async () => {
      const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
      store.reprocess = vi.fn().mockRejectedValue({ code: "request_failed", message: "Couldn't reach the estimate service. Start it in the api folder." });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      expect(await screen.findByText(/Couldn't reach the estimate service/)).toBeInTheDocument();
    });

    it("only sends context notes to the engine, never a reference-only one", async () => {
      const store = makeStore({
        notes: [
          { ...NOTE, id: "ctx", usage: "context", appliedAt: null, title: "Feeds it" },
          { ...NOTE, id: "ref", usage: "reference", appliedAt: null, title: "Reference only note" },
        ],
      });
      store.reprocess = vi.fn().mockResolvedValue({ reclassified: 1, preserved: 0, added: 0, removed: 0 });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      await waitFor(() => expect(store.reprocess).toHaveBeenCalled());
      const sentNotes = engineClient.estimateProject.mock.calls[0][2];
      expect(sentNotes).toHaveLength(1);
      expect(sentNotes[0].title).toBe("Feeds it");
    });

    it("re-sends an already-applied note, so a second run does not revert the first", async () => {
      // The regression guard for the worst bug this slice shipped. The
      // engine has no memory of a previous run's notes and the merge
      // overwrites every matched un-approved item from the payload it is
      // handed, so a payload built from the *unapplied* notes alone
      // silently reverts every earlier note's effect -- while the screen
      // still says "Used in this estimate" and the server re-stamps the
      // applied timestamp. A wrong bid total from using the feature
      // normally twice.
      const store = makeStore({
        notes: [
          { ...NOTE, id: "a", usage: "context", appliedAt: "2026-08-28T10:00:00Z", title: "Applied earlier" },
          { ...NOTE, id: "b", usage: "context", appliedAt: null, title: "Added just now" },
        ],
      });
      store.reprocess = vi.fn().mockResolvedValue({ reclassified: 2, preserved: 0, added: 0, removed: 0 });
      renderNotes({ store });
      await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
      await waitFor(() => expect(store.reprocess).toHaveBeenCalled());

      const sentNotes = engineClient.estimateProject.mock.calls[0][2];
      expect(sentNotes.map((n) => n.title).sort()).toEqual(["Added just now", "Applied earlier"]);
    });
  });

  it("says plainly when no source drawings remain to re-run, rather than failing obscurely", async () => {
    // The common case: ProcessingStatus.jsx clears the uploaded-files map
    // right after the project's first successful process, so by the time
    // an estimator adds a note and comes back here, this browser simply
    // doesn't hold the drawings in memory any more.
    clearUploadedFiles("p1");
    const store = makeStore({ notes: [{ ...NOTE, usage: "context", appliedAt: null }] });
    renderNotes({ store });
    await userEvent.click(await screen.findByRole("button", { name: /apply notes and re-run/i }));
    expect(await screen.findByText(/no source drawings|drawings aren't available|upload/i)).toBeInTheDocument();
    expect(store.reprocess).not.toHaveBeenCalled();
  });
});
