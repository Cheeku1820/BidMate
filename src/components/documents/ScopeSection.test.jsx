/* ============================================================
   ScopeSection.test.jsx — the scope the documents state, settled by a
   person on screen D. What matters: the statements are summarised and
   grouped by kind, the verbatim source is a click away, every decision
   goes through store.decideScope, and a statement's status is drawn in
   the note-status vocabulary -- never as one of the four review labels.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ScopeSection from "./ScopeSection.jsx";

const stmt = (o) => ({
  id: "s1",
  kind: "excluded",
  text: "Site lighting and pole bases.",
  editedText: null,
  status: "found",
  documentId: "d",
  documentFilename: "scope.pdf",
  page: 3,
  quote: "- Site lighting and pole bases.",
  ...o,
});

describe("ScopeSection", () => {
  it("summarises, groups by kind, and shows the source on demand", async () => {
    const store = {
      listScope: vi.fn().mockResolvedValue([stmt(), stmt({ id: "s2", kind: "included", text: "Provide all lighting.", status: "confirmed" })]),
      decideScope: vi.fn(),
    };
    render(<ScopeSection store={store} projectId="p" />);
    expect(await screen.findByText("2 statements found · 1 confirmed · 0 dismissed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Excluded" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Included" })).toBeInTheDocument();
    // Empty groups are omitted.
    expect(screen.queryByRole("heading", { name: "By others" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Alternates" })).toBeNull();
    expect(store.listScope).toHaveBeenCalledWith("p");
    await userEvent.click(screen.getAllByRole("button", { name: "View source" })[0]);
    expect(screen.getByText("- Site lighting and pole bases.")).toBeInTheDocument();
    expect(screen.getByText("scope.pdf, page 3")).toBeInTheDocument();
  });

  it("confirms, dismisses, and edits through the store", async () => {
    const decideScope = vi
      .fn()
      .mockImplementation((id, change) => Promise.resolve(stmt({ ...change, status: change.status ?? "found" })));
    const store = { listScope: vi.fn().mockResolvedValue([stmt()]), decideScope };
    render(<ScopeSection store={store} projectId="p" />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(decideScope).toHaveBeenCalledWith("s1", { status: "confirmed" });
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Statement" });
    await userEvent.clear(box);
    await userEvent.type(box, "Site lighting excluded; pole bases by GC.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(decideScope).toHaveBeenCalledWith("s1", { editedText: "Site lighting excluded; pole bases by GC." });
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(decideScope).toHaveBeenCalledWith("s1", { status: "dismissed" });
  });

  it("shows the edited sentence with the original beneath it, and offers the reverse action once decided", async () => {
    const decideScope = vi.fn().mockImplementation((id, change) => Promise.resolve(stmt({ ...change, status: change.status ?? "found" })));
    const store = { listScope: vi.fn().mockResolvedValue([stmt()]), decideScope };
    render(<ScopeSection store={store} projectId="p" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const box = screen.getByRole("textbox", { name: "Statement" });
    await userEvent.clear(box);
    await userEvent.type(box, "Pole bases by GC.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Pole bases by GC.")).toBeInTheDocument();
    expect(screen.getByText("Original: Site lighting and pole bases.")).toBeInTheDocument();

    // Confirmed: Dismiss and Edit remain, Confirm goes.
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByText("2 statements found · 1 confirmed · 0 dismissed".replace("2 statements", "1 statement"))).toBeInTheDocument();

    // Dismissed: Confirm and Edit remain, Dismiss goes.
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(await screen.findByText("Dismissed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByText("1 statement found · 0 confirmed · 1 dismissed")).toBeInTheDocument();
  });

  it("cancels an edit without writing, and keeps the row as it was when a decision fails", async () => {
    const decideScope = vi.fn().mockRejectedValue({ code: "network", message: "down" });
    const store = { listScope: vi.fn().mockResolvedValue([stmt()]), decideScope };
    render(<ScopeSection store={store} projectId="p" />);
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Statement" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(decideScope).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Site lighting and pole bases.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Couldn't save that decision. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByText("1 statement found · 0 confirmed · 0 dismissed")).toBeInTheDocument();
  });

  it("renders status as icon plus label, never the review-status classes", async () => {
    const store = { listScope: vi.fn().mockResolvedValue([stmt({ status: "confirmed" })]), decideScope: vi.fn() };
    const { container } = render(<ScopeSection store={store} projectId="p" />);
    expect(await screen.findByText("Confirmed")).toBeInTheDocument();
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
    const pill = container.querySelector(".note-status.note-status--confirmed");
    expect(pill).not.toBeNull();
    expect(pill.querySelector("svg")).not.toBeNull();
  });

  it("says so when there are no statements and when the list fails", async () => {
    render(<ScopeSection store={{ listScope: vi.fn().mockResolvedValue([]) }} projectId="p" />);
    expect(await screen.findByText("No scope statements were found in the documents.")).toBeInTheDocument();
    render(<ScopeSection store={{ listScope: vi.fn().mockRejectedValue(new Error("x")) }} projectId="p" />);
    expect(await screen.findByText("Couldn't load the scope statements. Check the connection and try again.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/loading/i)).toBeNull());
  });
});
