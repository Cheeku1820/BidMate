import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import QuestionLine from "./QuestionLine.jsx";

const q = (o) => ({
  key: "question:no_phasing:project", status: "found", title: "No phasing was stated",
  found: "The documents do not name any phase.", why: "A phased job is priced per phase.",
  fix: "Add the phases here, or answer that the job is one phase.", where: "Sheet titles and the specification.",
  documentId: null, documentFilename: null, noteId: null, ...o,
});

function mount(question, handlers = {}) {
  const h = { onAnswer: vi.fn().mockResolvedValue(undefined), onDismiss: vi.fn().mockResolvedValue(undefined), onReopen: vi.fn().mockResolvedValue(undefined), ...handlers };
  render(<MemoryRouter><QuestionLine question={question} notesHref="/projects/p1/notes" {...h} /></MemoryRouter>);
  return h;
}

describe("QuestionLine", () => {
  it("shows the four fields and the two controls", () => {
    mount(q());
    expect(screen.getByRole("heading", { name: "No phasing was stated" })).toBeInTheDocument();
    for (const text of ["The documents do not name any phase.", "A phased job is priced per phase.",
      "Add the phases here, or answer that the job is one phase.", "Sheet titles and the specification."]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Answer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });

  it("saves an answer through onAnswer and refuses an empty one", async () => {
    const h = mount(q());
    await userEvent.click(screen.getByRole("button", { name: "Answer" }));
    const save = screen.getByRole("button", { name: "Save answer" });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Your answer" }), "One phase, whole shop at once.");
    await userEvent.click(save);
    expect(h.onAnswer).toHaveBeenCalledWith("One phase, whole shop at once.");
  });

  it("reads Answered with a link to the note, and offers Reopen", async () => {
    const h = mount(q({ status: "answered", noteId: "n1" }));
    expect(screen.getByText("Answered")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See the note" })).toHaveAttribute("href", "/projects/p1/notes");
    expect(screen.queryByRole("button", { name: "Answer" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reopen" }));
    expect(h.onReopen).toHaveBeenCalled();
  });

  it("dismisses, and says so when a write fails", async () => {
    const h = mount(q(), { onDismiss: vi.fn().mockRejectedValue({ message: "down" }) });
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(h.onDismiss).toHaveBeenCalled();
    expect(await screen.findByText("Couldn't save that decision. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
  });

  it("shows a server refusal's own message when it carries a code", async () => {
    const h = mount(q(), {
      onAnswer: vi.fn().mockRejectedValue({
        code: "plan_question_answered",
        message: "This question already has an answer. Reopen it to answer it again.",
      }),
    });
    await userEvent.click(screen.getByRole("button", { name: "Answer" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Your answer" }), "One phase, whole shop at once.");
    await userEvent.click(screen.getByRole("button", { name: "Save answer" }));
    expect(h.onAnswer).toHaveBeenCalled();
    expect(await screen.findByText("This question already has an answer. Reopen it to answer it again.")).toBeInTheDocument();
  });

  it("never uses the review-status classes", () => {
    const { container } = render(<MemoryRouter><QuestionLine question={q({ status: "dismissed" })} notesHref="/n" onAnswer={vi.fn()} onDismiss={vi.fn()} onReopen={vi.fn()} /></MemoryRouter>);
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
    expect(container.querySelector(".note-status--dismissed")).not.toBeNull();
  });
});
