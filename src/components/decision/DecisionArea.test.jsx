import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import DecisionArea from "./DecisionArea.jsx";

const item = { id: "i1", name: "Luminaire type F", quantity: 30, unit: "ea", status: "attention", rejected: false,
  system: "Lighting", category: "Fixtures", sourceTag: "F", approvedBy: null, approvedAt: null, resolveNote: null, rejectReason: null, path: null };
const proposal = { intent: "reclassify", targetItemIds: ["i1", "i2", "i3"], name: "2x4 LED troffer, 4000K — type F", system: "Lighting",
  category: "Fixtures", unit: "ea", catalogId: null, scheduleMatch: { sheet: "E-501", line: "F" }, quantity: 28, rejectReason: null,
  summary: "Applies to all 3", source: "read", versions: { i1: 1, i2: 1, i3: 1 } };

function setup(over = {}) {
  const onResolve = over.props?.onResolve ?? vi.fn().mockResolvedValue(proposal);
  const onApply = over.props?.onApply ?? vi.fn().mockResolvedValue({ label: "Approved 3 × 2x4 LED troffer, 4000K — type F", alsoMatching: { count: 6, sheetNumbers: ["EL101"] } });
  const onUndo = vi.fn(); const onSelectItem = vi.fn();
  const mergedItem = { ...item, ...over.item };
  const { rerender } = render(<DecisionArea item={mergedItem} sheetNumber="EP101" onResolve={onResolve} onApply={onApply} onUndo={onUndo} onSelectItem={onSelectItem} alsoMatchingItemId="i9" {...over.props} />);
  return { onResolve, onApply, onUndo, onSelectItem, rerender, mergedItem };
}

describe("DecisionArea", () => {
  it("starts on the box, focused, with the reading and the two reject chips", () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    expect(document.activeElement).toBe(box);
    expect(screen.getByRole("button", { name: "Luminaire type F" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not a device" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Existing to remain" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve item/i })).not.toBeInTheDocument();
  });

  it("Enter resolves the sentence and shows the card without writing", async () => {
    const { onResolve, onApply } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "2x4 LED troffer, type F on E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await waitFor(() => expect(screen.getByText("2x4 LED troffer, 4000K — type F")).toBeInTheDocument());
    expect(onResolve).toHaveBeenCalledWith("2x4 LED troffer, type F on E-501");
    expect(screen.getByText(/Applies to all 30 · renames "Luminaire type F" · count 30 → 28 · clears the warning/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and approve 28" })).toBeInTheDocument();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("confirm and approve applies with approve true and the sentence as the note, then shows the statement", async () => {
    const { onApply } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(proposal, { approve: true, note: "type F per E-501" }));
    await waitFor(() => expect(screen.getByText(/You approved 28 ea/)).toBeInTheDocument());
    expect(screen.getByText(/From your note: "type F per E-501"/)).toBeInTheDocument();
    expect(screen.getByText(/6 more F on EL101 read the same way/)).toBeInTheDocument();
  });

  it("a reject chip yields the reject card and applies as an exclusion with the chip text as reason", async () => {
    const reject = { ...proposal, intent: "exclude", rejectReason: "Not a device", quantity: null, targetItemIds: ["i1"] };
    const { onResolve, onApply } = setup({ props: { onResolve: vi.fn().mockResolvedValue(reject) } });
    fireEvent.click(screen.getByRole("button", { name: "Not a device" }));
    await waitFor(() => expect(onResolve).toHaveBeenCalledWith("Not a device"));
    expect(await screen.findByText("Applies to all 30 on EP101")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Reject 30" }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(reject, { approve: false, note: "Not a device" }));
  });

  it("empty Enter on a Ready to review item submits the reading", async () => {
    const { onResolve } = setup({ item: { status: "ready" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "What is this?" }), { key: "Enter" });
    await waitFor(() => expect(onResolve).toHaveBeenCalledWith("Luminaire type F"));
  });

  it("empty Enter on an unclassified item does nothing and shows the helper", () => {
    const { onResolve } = setup({ item: { category: "Unclassified", name: "Unclassified symbol (TOP)" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "What is this?" }), { key: "Enter" });
    expect(onResolve).not.toHaveBeenCalled();
    expect(screen.getByText("Say what it is, or pick one above.")).toBeInTheDocument();
  });

  it("a typed proposal shows the custom-item line and still approves", async () => {
    const typed = { ...proposal, source: "typed", name: "patient headwalls", scheduleMatch: null, quantity: null };
    setup({ props: { onResolve: vi.fn().mockResolvedValue(typed) } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "patient headwalls" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByText("Read from your words as a custom item.");
    expect(screen.getByRole("button", { name: "Confirm and approve 30" })).toBeInTheDocument();
  });

  it("an unknown proposal shows the couldn't-read copy and no apply button", async () => {
    setup({ props: { onResolve: vi.fn().mockResolvedValue({ ...proposal, intent: "unknown" }) } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "hmm" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByText(/Couldn't read that/);
    expect(screen.queryByRole("button", { name: /Confirm/ })).not.toBeInTheDocument();
  });

  it("Escape on the card returns to the box with the sentence intact", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    const card = await screen.findByRole("group", { name: "Proposal" });
    fireEvent.keyDown(card, { key: "Escape" });
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F");
  });

  it("Escape works while the card is open even without focus on it", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("group", { name: "Proposal" });
    document.body.focus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F");
  });

  it("Change wording returns to the box with the sentence intact", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Change wording" }));
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F");
  });

  it("an already-approved item opens on the statement", () => {
    setup({ item: { status: "approved", approvedBy: "Dana", approvedAt: "2026-09-18T14:41:00Z", resolveNote: "type F per E-501" } });
    expect(screen.getByText(/You approved 30 ea/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "What is this?" })).not.toBeInTheDocument();
  });

  it("an already-rejected item opens on the rejected statement", () => {
    setup({ item: { rejected: true, rejectReason: "Not a device" } });
    expect(screen.getByText(/You rejected 30 — "Not a device"/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "What is this?" })).not.toBeInTheDocument();
  });

  it("responds to decision-cmd events for A and R", async () => {
    const { onResolve } = setup();
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "reject" } })); });
    await waitFor(() => expect(onResolve).toHaveBeenCalledWith("Not a device"));
  });

  it("the confirm decision-cmd on the card applies the proposal", async () => {
    const { onApply } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("button", { name: "Confirm and approve 28" });
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "confirm" } })); });
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(proposal, { approve: true, note: "type F per E-501" }));
  });

  it("the focus decision-cmd focuses the box", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("button", { name: "Confirm and approve 28" });
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "focus" } })); });
    await waitFor(() => expect(screen.getByRole("textbox", { name: "What is this?" })).toBe(document.activeElement));
  });

  it("guards against double submission while a resolve is pending", async () => {
    let resolveFn;
    const pending = new Promise((res) => { resolveFn = res; });
    const onResolve = vi.fn().mockReturnValue(pending);
    setup({ props: { onResolve } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Luminaire type F" }));
    expect(onResolve).toHaveBeenCalledTimes(1);
    await act(async () => { resolveFn(proposal); await pending; });
  });

  it("guards against double-apply from repeated confirm commands", async () => {
    let resolveApply;
    const pendingApply = new Promise((res) => { resolveApply = res; });
    const onApply = vi.fn().mockReturnValue(pendingApply);
    setup({ props: { onApply } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("button", { name: "Confirm and approve 28" });
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "confirm" } })); });
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "confirm" } })); });
    expect(onApply).toHaveBeenCalledTimes(1);
    await act(async () => { resolveApply({ label: "x", alsoMatching: null }); await pendingApply; });
  });

  it("a status change on the same item does not wipe the statement (store refresh after apply)", async () => {
    const { onApply, rerender, mergedItem } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await screen.findByText(/You approved 28 ea/);
    rerender(<DecisionArea item={{ ...mergedItem, status: "approved" }} sheetNumber="EP101" onResolve={vi.fn()} onApply={onApply} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    expect(screen.getByText(/You approved 28 ea/)).toBeInTheDocument();
    expect(screen.getByText(/From your note: "type F per E-501"/)).toBeInTheDocument();
    expect(screen.getByText(/6 more F on EL101 read the same way/)).toBeInTheDocument();
  });

  it("undo from the statement returns to the box with the sentence intact, without waiting on a refresh", async () => {
    const { onUndo } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await screen.findByText(/You approved 28 ea/);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F per E-501");
  });

  it("confirm, keep reviewing shows the neutral statement without approving", async () => {
    const { onApply } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm, keep reviewing" }));
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(proposal, { approve: false, note: "type F per E-501" }));
    expect(await screen.findByText(/You read this as 2x4 LED troffer, 4000K — type F/)).toBeInTheDocument();
  });

  it("shows the rejected statement after applying a rejection", async () => {
    const reject = { ...proposal, intent: "exclude", rejectReason: "Not a device", quantity: null, targetItemIds: ["i1"] };
    const onApply = vi.fn().mockResolvedValue({ label: "Rejected", alsoMatching: null });
    setup({ props: { onResolve: vi.fn().mockResolvedValue(reject), onApply } });
    fireEvent.click(screen.getByRole("button", { name: "Not a device" }));
    fireEvent.click(await screen.findByRole("button", { name: "Reject 30" }));
    await waitFor(() => expect(onApply).toHaveBeenCalled());
    expect(await screen.findByText(/You rejected 30 — "Not a device"/)).toBeInTheDocument();
  });

  it("a measured item's proposal card omits the count from the changes line and the button", async () => {
    setup({ item: { path: "M 10 10 L 90 90", quantity: 42 }, props: { onResolve: vi.fn().mockResolvedValue({ ...proposal, quantity: 40 }) } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "conduit run" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await screen.findByRole("button", { name: "Confirm and approve" });
    expect(screen.getByText(/Applies to all 42 · renames "Luminaire type F" · clears the warning/)).toBeInTheDocument();
    expect(screen.queryByText(/count 42 → 40/)).not.toBeInTheDocument();
  });
});
