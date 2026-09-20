import { describe, expect, test, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useReviewStore } from "./useReviewStore.js";

describe("useReviewStore", () => {
  test("exposes runMutation and showToast for screens outside the snapshot", () => {
    const store = {
      getSnapshot: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn(() => () => {}),
      setPresence: vi.fn().mockResolvedValue(),
    };
    const { result } = renderHook(() => useReviewStore(store, { onSignedOut: () => {} }));
    expect(typeof result.current.runMutation).toBe("function");
    expect(typeof result.current.showToast).toBe("function");
  });

  test("applyProposal sets the returned snapshot and toasts the label", async () => {
    const snapshot = { version: "v2", sheets: [], items: [], totals: {}, undo: {}, presence: [] };
    const store = {
      getSnapshot: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn(() => () => {}),
      setPresence: vi.fn().mockResolvedValue(),
      applyProposal: vi.fn().mockResolvedValue({ label: "Approved 2 × x", snapshot, alsoMatching: { count: 0, sheetNumbers: [] } }),
    };
    // A stable options object: the render callback below is invoked on
    // every re-render (renderHook wraps it as the "component" under
    // test), and a fresh `{ onSignedOut }` literal each time gives
    // handleSignedOut, then refresh, then the poll effect's deps a new
    // identity every render -- which re-fires refresh() after every
    // state change and stomps the snapshot applyProposal just set.
    const options = { onSignedOut: () => {} };
    const { result } = renderHook(() => useReviewStore(store, options));

    // Let the mount effect's own getSnapshot() (resolves null here)
    // settle before applying the proposal, so it cannot stomp on the
    // snapshot applyProposal is about to set. A macrotask flush drains
    // every pending microtask in that chain, where a bare awaited
    // Promise.resolve() would only advance one tick at a time.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));

    await act(async () => {
      await result.current.applyProposal("i1", { intent: "reclassify" }, { approve: true, note: "" });
    });

    expect(result.current.snapshot).toBe(snapshot);
    expect(result.current.toast.text).toBe("Approved 2 × x");
  });
});
