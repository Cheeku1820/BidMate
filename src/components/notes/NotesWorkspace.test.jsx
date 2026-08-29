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

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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
  };
}

let context;

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

function renderNotes({ notes = [], store = makeStore({ notes }) } = {}) {
  context = {
    store,
    projectId: "p1",
    me: { id: "u1", name: "Dana Whitfield" },
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
});
