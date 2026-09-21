import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PhaseSection from "./PhaseSection.jsx";

const detected = { key: "phase:PHASE 1", kind: "phase", text: "Phase 1", foundText: "Phase 1", editedText: null, status: "found",
  documentId: "d", documentFilename: "E-set.pdf", page: 2, quote: "Phase 1 demolition plan", division: null, sheetNumber: null,
  added: false, phaseId: null, places: [
    { documentId: "d", documentFilename: "E-set.pdf", page: 2, quote: "Phase 1 demolition plan" },
    { documentId: "d", documentFilename: "E-set.pdf", page: 5, quote: "PHASE 1 POWER PLAN" },
  ] };
const added = { ...detected, key: "phase:added:ph1", text: "Phase 3 — office", foundText: "Phase 3 — office", documentId: null,
  documentFilename: null, page: null, quote: null, added: true, phaseId: "ph1", places: [] };

describe("PhaseSection", () => {
  it("lists detected phases with every place they appear, and added ones as stated by you", () => {
    render(<PhaseSection phases={[detected, added]} onDecide={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText("Phase 1")).toBeInTheDocument();
    expect(screen.getByText("E-set.pdf, page 5")).toBeInTheDocument();
    expect(screen.getByText("Phase 3 — office")).toBeInTheDocument();
    expect(screen.getByText("Stated by you")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("says so when the documents state no phase", () => {
    render(<PhaseSection phases={[]} onDecide={vi.fn()} onAdd={vi.fn()} onRemove={vi.fn()} />);
    expect(screen.getByText("The documents do not name any phase.")).toBeInTheDocument();
  });

  it("adds a phase by name, clears the field, and shows a refusal inline", async () => {
    const onAdd = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce({ message: "That phase is already on the plan." });
    render(<PhaseSection phases={[]} onDecide={vi.fn()} onAdd={onAdd} onRemove={vi.fn()} />);
    const field = screen.getByRole("textbox", { name: "Phase name" });
    const button = screen.getByRole("button", { name: "Add phase" });
    expect(button).toBeDisabled();
    await userEvent.type(field, "Phase 2");
    await userEvent.click(button);
    expect(onAdd).toHaveBeenCalledWith("Phase 2");
    expect(field).toHaveValue("");
    await userEvent.type(field, "Phase 2");
    await userEvent.click(screen.getByRole("button", { name: "Add phase" }));
    expect(await screen.findByText("That phase is already on the plan.")).toBeInTheDocument();
  });

  it("routes a decision and a removal to the right handler", async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined);
    const onRemove = vi.fn().mockResolvedValue(undefined);
    render(<PhaseSection phases={[detected, added]} onDecide={onDecide} onAdd={vi.fn()} onRemove={onRemove} />);
    await userEvent.click(screen.getAllByRole("button", { name: "Confirm" })[0]);
    expect(onDecide).toHaveBeenCalledWith("phase:PHASE 1", { status: "confirmed" });
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onRemove).toHaveBeenCalledWith("ph1");
  });
});
