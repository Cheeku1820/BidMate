/* PlanLine — one line of the plan: its status in the note-status
   vocabulary, its text (corrected or as found), the page it came from,
   and the decision controls. Shared by scope statements and every
   derived line, so the same words appear on every row. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlanLine from "./PlanLine.jsx";
import { documentPageHref } from "./pageLink.js";

const line = (o) => ({
  key: "schedule:sheet:s1", status: "found", text: "Luminaire schedule", editedText: null,
  quote: "LUMINAIRE SCHEDULE", documentId: "d1", documentFilename: "E-set.pdf", page: 2, ...o,
});

describe("documentPageHref", () => {
  it("opens the document at the page, or the document alone", () => {
    expect(documentPageHref("d1", 3)).toBe("/api/documents/d1/content#page=3");
    expect(documentPageHref("d1", null)).toBe("/api/documents/d1/content");
    expect(documentPageHref(null, 3)).toBe("");
  });
});

describe("PlanLine", () => {
  it("shows the text, the cite with a page link, and the source on demand", async () => {
    render(<PlanLine line={line()} onDecide={vi.fn()} />);
    expect(screen.getByText("Luminaire schedule")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open page" });
    expect(link).toHaveAttribute("href", "/api/documents/d1/content#page=2");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("E-set.pdf, page 2")).toBeInTheDocument();
    expect(screen.queryByText("LUMINAIRE SCHEDULE")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "View source" }));
    expect(screen.getByText("LUMINAIRE SCHEDULE")).toBeInTheDocument();
  });

  it("cites the document alone when there is no page, and nothing when there is no document", () => {
    const { rerender } = render(<PlanLine line={line({ page: null, documentFilename: "Spec.pdf" })} onDecide={vi.fn()} />);
    expect(screen.getByText("Spec.pdf")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open document" })).toHaveAttribute("href", "/api/documents/d1/content");
    rerender(<PlanLine line={line({ documentId: null, documentFilename: null, page: null, quote: null, added: true })} onDecide={vi.fn()} />);
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button", { name: "View source" })).toBeNull();
    expect(screen.getByText("Stated by you")).toBeInTheDocument();
  });

  it("confirms, corrects, dismisses and reopens through onDecide", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    const { rerender } = render(<PlanLine line={line()} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "confirmed" });
    await userEvent.click(screen.getByRole("button", { name: "Correct" }));
    const box = screen.getByRole("textbox", { name: "Statement" });
    await userEvent.clear(box);
    await userEvent.type(box, "Luminaire schedule (sheet E0.1)");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onDecide).toHaveBeenCalledWith({ editedText: "Luminaire schedule (sheet E0.1)" });
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "dismissed" });
    rerender(<PlanLine line={line({ status: "dismissed", editedText: "Luminaire schedule (sheet E0.1)" })} onDecide={onDecide} />);
    expect(screen.getByText("Luminaire schedule (sheet E0.1)")).toBeInTheDocument();
    expect(screen.getByText("Original: Luminaire schedule")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
    expect(onDecide).toHaveBeenCalledWith({ status: "found" });
  });

  it("keeps the row as it was and says so when a decision fails, and cancels an edit without writing", async () => {
    const onDecide = vi.fn().mockRejectedValue({ message: "down" });
    render(<PlanLine line={line()} onDecide={onDecide} />);
    await userEvent.click(screen.getByRole("button", { name: "Correct" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Statement" }), " more");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.queryByRole("textbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Couldn't save that decision. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
  });

  it("renders a Remove control and children when given", async () => {
    const onRemove = vi.fn().mockResolvedValue(undefined);
    render(
      <PlanLine line={line({ added: true, documentId: null, page: null, quote: null })} onDecide={vi.fn()} onRemove={onRemove}>
        <p>Also on E2.2</p>
      </PlanLine>,
    );
    expect(screen.getByText("Also on E2.2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalled();
  });

  it("renders status as icon plus label, never the review-status classes", () => {
    const { container } = render(<PlanLine line={line({ status: "confirmed" })} onDecide={vi.fn()} />);
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
    const pill = container.querySelector(".note-status.note-status--confirmed");
    expect(pill).not.toBeNull();
    expect(pill.querySelector("svg")).not.toBeNull();
  });
});
