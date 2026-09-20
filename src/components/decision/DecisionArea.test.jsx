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

  it("the focus decision-cmd focuses the box even when already on it (the common case)", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    box.blur();
    expect(document.activeElement).not.toBe(box);
    act(() => { window.dispatchEvent(new CustomEvent("decision-cmd", { detail: { type: "focus" } })); });
    await waitFor(() => expect(document.activeElement).toBe(box));
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

  it("a Ctrl+Z undo that contradicts a local approval drops the statement back to the box (green never lingers on an unapproved item)", async () => {
    const { onApply, rerender, mergedItem } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await screen.findByText(/You approved 28 ea/);
    const rerenderProps = { sheetNumber: "EP101", onResolve: vi.fn(), onApply, onUndo: vi.fn(), onSelectItem: vi.fn(), alsoMatchingItemId: "i9" };
    // the store confirms the apply first — must change nothing (finding 1's case)
    rerender(<DecisionArea item={{ ...mergedItem, status: "approved" }} {...rerenderProps} />);
    expect(screen.getByText(/You approved 28 ea/)).toBeInTheDocument();
    // ...then a later Ctrl+Z reverses it — the statement must not linger
    rerender(<DecisionArea item={{ ...mergedItem, status: "attention" }} {...rerenderProps} />);
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F per E-501");
    expect(screen.queryByText(/You approved/)).not.toBeInTheDocument();
  });

  it("an item that becomes approved while idle opens on the item-derived statement (a teammate's action)", async () => {
    const { rerender, mergedItem } = setup({ item: { status: "ready" } });
    screen.getByRole("textbox", { name: "What is this?" }); // idle on the box, no local statement
    const updated = { ...mergedItem, status: "approved", approvedBy: "Dana", approvedAt: "2026-09-18T14:41:00Z", resolveNote: "type F per E-501" };
    rerender(<DecisionArea item={updated} sheetNumber="EP101" onResolve={vi.fn()} onApply={vi.fn()} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    expect(await screen.findByText(/You approved 30 ea/)).toBeInTheDocument();
  });

  it("an item-derived statement returns to the box if the item stops being approved or rejected", () => {
    const { rerender, mergedItem } = setup({ item: { status: "approved", approvedBy: "Dana", approvedAt: "2026-09-18T14:41:00Z", resolveNote: "type F per E-501" } });
    expect(screen.getByText(/You approved 30 ea/)).toBeInTheDocument();
    const updated = { ...mergedItem, status: "attention", approvedBy: null, approvedAt: null, resolveNote: null };
    rerender(<DecisionArea item={updated} sheetNumber="EP101" onResolve={vi.fn()} onApply={vi.fn()} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    expect(screen.getByRole("textbox", { name: "What is this?" })).toBeInTheDocument();
  });

  it("Escape on the focused card stops the keypress from also reaching a window-level listener", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    const card = await screen.findByRole("group", { name: "Proposal" });
    const spy = vi.fn();
    window.addEventListener("keydown", spy);
    fireEvent.keyDown(card, { key: "Escape", bubbles: true });
    window.removeEventListener("keydown", spy);
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F");
  });

  it("a resolve that returns after the estimator moved to another item is discarded, not shown as that item's card", async () => {
    let resolveFn;
    const pending = new Promise((res) => { resolveFn = res; });
    const onResolve = vi.fn().mockReturnValue(pending);
    const { rerender, mergedItem } = setup({ props: { onResolve } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    const itemB = { ...mergedItem, id: "i2", name: "Unclassified symbol (TOP)" };
    rerender(<DecisionArea item={itemB} sheetNumber="EP101" onResolve={onResolve} onApply={vi.fn()} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    await act(async () => { resolveFn(proposal); await pending; });
    expect(screen.queryByRole("group", { name: "Proposal" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Read this" })).toBeEnabled();
  });

  it("an apply that returns after the estimator moved to another item never shows a green statement on that item", async () => {
    let resolveApply;
    const pendingApply = new Promise((res) => { resolveApply = res; });
    const onApply = vi.fn().mockReturnValue(pendingApply);
    const { rerender, mergedItem } = setup({ props: { onApply } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    expect(onApply).toHaveBeenCalledTimes(1);
    const itemB = { ...mergedItem, id: "i2", status: "attention" };
    rerender(<DecisionArea item={itemB} sheetNumber="EP101" onResolve={vi.fn()} onApply={onApply} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    await act(async () => { resolveApply({ label: "Approved 28 × 2x4 LED troffer", alsoMatching: { count: 0, sheetNumbers: [] } }); await pendingApply; });
    expect(screen.queryByText(/You approved/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "What is this?" })).toBeInTheDocument();
  });

  it("a failed read says so, names the recovery, and leaves the box usable", async () => {
    const onResolve = vi.fn().mockRejectedValue(new Error("network"));
    setup({ props: { onResolve } });
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(await screen.findByText("Couldn't read that right now — try again.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "What is this?" })).toHaveValue("type F");
    expect(screen.getByRole("button", { name: "Read this" })).toBeEnabled();
    expect(screen.queryByRole("group", { name: "Proposal" })).not.toBeInTheDocument();
    // and the next attempt goes out
    fireEvent.keyDown(screen.getByRole("textbox", { name: "What is this?" }), { key: "Enter" });
    await waitFor(() => expect(onResolve).toHaveBeenCalledTimes(2));
  });

  it("an item-derived statement offers Change but not Undo (the shared undo would reverse an unrelated action)", () => {
    setup({ item: { status: "approved", approvedBy: "Dana", approvedAt: "2026-09-18T14:41:00Z", resolveNote: "type F per E-501" } });
    expect(screen.getByText(/You approved 30 ea/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change" })).toBeInTheDocument();
  });

  it("an item-derived rejected statement offers Change but not Undo", () => {
    setup({ item: { rejected: true, rejectReason: "Not a device" } });
    expect(screen.queryByRole("button", { name: "Undo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change" })).toBeInTheDocument();
  });

  it("a statement produced by this area's own apply offers Undo", async () => {
    setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await screen.findByText(/You approved 28 ea/);
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change" })).toBeInTheDocument();
  });

  it("selecting an already-rejected item right after a local approval shows its own statement, not a stale box (the id/status race)", async () => {
    const { onApply, rerender, mergedItem } = setup();
    const box = screen.getByRole("textbox", { name: "What is this?" });
    fireEvent.change(box, { target: { value: "type F per E-501" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Confirm and approve 28" }));
    await screen.findByText(/You approved 28 ea/);
    const itemB = { ...mergedItem, id: "i2", rejected: true, rejectReason: "not a device" };
    rerender(<DecisionArea item={itemB} sheetNumber="EP101" onResolve={vi.fn()} onApply={onApply} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    expect(await screen.findByText(/You rejected 30 — "not a device"/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "What is this?" })).not.toBeInTheDocument();
  });

  it("selecting an already-approved item right after a local rejection shows its own statement, not a stale box (the id/status race)", async () => {
    const reject = { ...proposal, intent: "exclude", rejectReason: "Not a device", quantity: null, targetItemIds: ["i1"] };
    const onApply = vi.fn().mockResolvedValue({ label: "Rejected", alsoMatching: null });
    const { rerender, mergedItem } = setup({ props: { onResolve: vi.fn().mockResolvedValue(reject), onApply } });
    fireEvent.click(screen.getByRole("button", { name: "Not a device" }));
    fireEvent.click(await screen.findByRole("button", { name: "Reject 30" }));
    await screen.findByText(/You rejected 30/);
    const itemB = { ...mergedItem, id: "i2", rejected: false, rejectReason: null, status: "approved", approvedBy: "Dana", approvedAt: "2026-09-18T14:41:00Z", resolveNote: "type F per E-501" };
    rerender(<DecisionArea item={itemB} sheetNumber="EP101" onResolve={vi.fn()} onApply={onApply} onUndo={vi.fn()} onSelectItem={vi.fn()} alsoMatchingItemId="i9" />);
    expect(await screen.findByText(/You approved 30 ea/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "What is this?" })).not.toBeInTheDocument();
  });
});
