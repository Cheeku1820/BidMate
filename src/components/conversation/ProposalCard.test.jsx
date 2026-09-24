/* The card: what would change, where it lands, and the two controls.
   It renders and reports — every write goes through the record's own
   endpoint, which applyProposal.js maps and this component never
   touches. A card's words are its own: offered, applied, dismissed,
   stale — never the four review labels. */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProposalCard from "./ProposalCard.jsx";
import { applyProposal } from "./applyProposal.js";

const item = (o) => ({
  kind: "item", summary: "Name 6 items on E2.1 2x4 LED troffer, type F.", note: "Approving stays with you.",
  count: 6, sheetNumber: "E2.1", itemId: "i1", approve: false,
  proposal: { intent: "reclassify", target_item_ids: ["i1"], versions: { i1: 1 }, name: "2x4 LED troffer, type F" },
  targetsPreview: [{ label: "Unclassified symbol", detail: "6 EA" }, { label: "Unclassified symbol", detail: "2 EA" }],
  moreCount: 4, ...o,
});

const note = (o) => ({ kind: "note", summary: "Add a note to this project: Ceiling is 14 feet",
  title: "Ceiling is 14 feet", body: "Ceiling is 14 feet in the warehouse.", category: "existing_condition",
  usage: "context", targetsPreview: [], moreCount: 0, ...o });

function mount(proposal, status = "offered", handlers = {}) {
  const h = { onApply: vi.fn(), onDismiss: vi.fn(), ...handlers };
  render(<ProposalCard proposal={proposal} status={status} {...h} />);
  return h;
}

describe("ProposalCard", () => {
  it("shows what would change, the preview and the remainder", () => {
    mount(item());
    expect(screen.getByText("Name 6 items on E2.1 2x4 LED troffer, type F.")).toBeInTheDocument();
    expect(screen.getAllByText("Unclassified symbol")).toHaveLength(2);
    expect(screen.getByText("+4 more")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
  });

  it("always says approving stays with the estimator on an item card", () => {
    mount(item());
    expect(screen.getByText("Approving stays with you.")).toBeInTheDocument();
  });

  it("a note card names where it lands and carries no item language", () => {
    mount(note());
    expect(screen.getByText("Add a note to this project: Ceiling is 14 feet")).toBeInTheDocument();
    expect(screen.getByText("Ceiling is 14 feet in the warehouse.")).toBeInTheDocument();
    expect(screen.queryByText("Approving stays with you.")).toBeNull();
  });

  it("reports Apply and Dismiss without calling anything itself", async () => {
    const h = mount(item());
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(h.onApply).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(h.onDismiss).toHaveBeenCalled();
  });

  it("states the outcome once settled, and offers nothing when stale", () => {
    const { unmount } = render(<ProposalCard proposal={item()} status="applied" onApply={vi.fn()} onDismiss={vi.fn()} />);
    expect(screen.getByText("Applied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
    unmount();
    mount(item(), "stale");
    expect(screen.getByText(/have moved on/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("a refusal has no Apply", () => {
    mount({ kind: "refused", summary: "That would change 120 items. Narrow it down — filter the view, or pick a sheet.",
            targetsPreview: [], moreCount: 0 });
    expect(screen.getByText(/Narrow it down/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("never uses the review-status classes", () => {
    const { container } = render(<ProposalCard proposal={item()} status="offered" onApply={vi.fn()} onDismiss={vi.fn()} />);
    expect(container.querySelector(".pill--approved, .pill--ready, .pill--attention, .pill--missing")).toBeNull();
  });
});

describe("applyProposal", () => {
  const store = () => ({
    applyProposal: vi.fn().mockResolvedValue({}), createNote: vi.fn().mockResolvedValue({}),
    decideScope: vi.fn().mockResolvedValue({}), decidePlanLine: vi.fn().mockResolvedValue({}),
    answerPlanQuestion: vi.fn().mockResolvedValue({}),
  });

  // NOTE: the brief's table describes store.applyProposal as a 2-arg call
  // (itemId, { proposal, approve, note }). The real store
  // (src/lib/store/api.js:341) takes THREE positional arguments —
  // applyProposal(itemId, proposal, { approve, note }) — so this
  // assertion follows the real signature rather than the table, per the
  // brief's own instruction to verify and follow the code. See the task
  // report for detail.
  it("an item goes to apply-proposal, never approving", async () => {
    const s = store();
    await applyProposal(s, "p1", item());
    expect(s.applyProposal).toHaveBeenCalledWith(
      "i1",
      expect.objectContaining({ name: "2x4 LED troffer, type F" }),
      { approve: false, note: null },
    );
  });

  it("a note goes to createNote as a context note", async () => {
    const s = store();
    await applyProposal(s, "p1", note());
    expect(s.createNote).toHaveBeenCalledWith("p1", expect.objectContaining({ usage: "context", scope: "project",
      title: "Ceiling is 14 feet", category: "existing_condition" }));
  });

  it("scope, plan line and plan answer each go to their own endpoint", async () => {
    const s = store();
    await applyProposal(s, "p1", { kind: "scope", statementId: "s1", status: "confirmed" });
    expect(s.decideScope).toHaveBeenCalledWith("s1", { status: "confirmed" });
    await applyProposal(s, "p1", { kind: "scope", statementId: "s1", status: null, editedText: "Reworded." });
    expect(s.decideScope).toHaveBeenLastCalledWith("s1", { editedText: "Reworded." });
    await applyProposal(s, "p1", { kind: "plan_line", key: "spec:d:260519", status: "confirmed" });
    expect(s.decidePlanLine).toHaveBeenCalledWith("p1", "spec:d:260519", { status: "confirmed" });
    await applyProposal(s, "p1", { kind: "plan_answer", key: "question:no_phasing:project", body: "One phase." });
    expect(s.answerPlanQuestion).toHaveBeenCalledWith("p1", "question:no_phasing:project", "One phase.");
  });

  it("a refusal or an unknown kind throws rather than guessing", async () => {
    const s = store();
    await expect(applyProposal(s, "p1", { kind: "refused" })).rejects.toBeTruthy();
    await expect(applyProposal(s, "p1", { kind: "price" })).rejects.toBeTruthy();
  });
});
