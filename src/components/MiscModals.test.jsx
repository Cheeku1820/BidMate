/* ============================================================
   MiscModals.test.jsx — EvidenceModal (task-11-brief.md): the source-
   evidence dialog must render the real per-item evidence image when
   one exists, fall back to text on a load error, and skip straight to
   the fallback for an item recorded with no image at all.
   ============================================================ */

import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { EvidenceModal } from "./MiscModals.jsx";

const baseItem = {
  id: "item-1", version: 1, symbol: "receptacle", status: "ready",
  evidence: { sheet: "E2.1", detail: "Counted from the drawing at 3 locations", has_image: true },
};

describe("EvidenceModal", () => {
  test("shows a real image when the item has one", () => {
    render(<EvidenceModal item={baseItem} onClose={() => {}} />);
    const img = screen.getByRole("img");
    expect(img.src).toContain("/api/items/item-1/evidence-image");
  });

  test("falls back to text when the image fails to load", () => {
    render(<EvidenceModal item={baseItem} onClose={() => {}} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.getByText(/no evidence recorded/i)).toBeInTheDocument();
  });

  test("shows the fallback directly for an item with no image", () => {
    const noImage = { ...baseItem, evidence: { ...baseItem.evidence, has_image: false } };
    render(<EvidenceModal item={noImage} onClose={() => {}} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText(/no evidence recorded/i)).toBeInTheDocument();
  });
});
