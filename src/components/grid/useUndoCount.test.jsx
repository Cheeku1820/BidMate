import { describe, expect, test, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useUndoCount } from "./useUndoCount.js";

describe("useUndoCount", () => {
  test("reverses one action by default, then reloads, with no extra toast", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).not.toHaveBeenCalled();
  });

  test("reverses every call the last toast stood for, newest first, then says so, then resets, when the toast text still matches", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    act(() => result.current.remember({ calls: 3, cells: 5, text: "Pasted 5 cells on 2 rows" }));
    await act(() => result.current.undoLast("Pasted 5 cells on 2 rows"));
    expect(undo).toHaveBeenCalledTimes(3);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith("Reversed 5 cells");
    // Reset after use: a second Undo on whatever toast is now up is one call.
    await act(() => result.current.undoLast("Pasted 5 cells on 2 rows"));
    expect(undo).toHaveBeenCalledTimes(4);
  });

  test("a different toast's Undo reverses one action, not the remembered count", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    act(() => result.current.remember({ calls: 6, cells: 6, text: "Pasted 6 cells on 6 rows" }));
    // A different toast -- e.g. the review store's own "Undid …" toast --
    // is now the one on screen; its Undo must not spend the remembered count.
    await act(() => result.current.undoLast("Undid Set price to $12.50 on 20A duplex receptacle"));
    expect(undo).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).not.toHaveBeenCalled();
  });

  test("stops when the stack runs dry, and a rejection still reloads before it reaches the caller", async () => {
    const undo = vi.fn().mockResolvedValueOnce({ performed: true }).mockResolvedValueOnce({ performed: false });
    const load = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast: vi.fn() }));
    act(() => result.current.remember({ calls: 4, cells: 4, text: "Pasted 4 cells on 4 rows" }));
    await act(() => result.current.undoLast("Pasted 4 cells on 4 rows"));
    expect(undo).toHaveBeenCalledTimes(2);

    const failingUndo = vi.fn().mockRejectedValue(new Error("Nothing to undo"));
    const failingLoad = vi.fn().mockResolvedValue(undefined);
    const failing = renderHook(() => useUndoCount({ undo: failingUndo, load: failingLoad, showToast: vi.fn() }));
    act(() => failing.result.current.remember({ calls: 3, cells: 3, text: "Pasted 3 cells on 3 rows" }));
    await expect(act(() => failing.result.current.undoLast("Pasted 3 cells on 3 rows"))).rejects.toThrow("Nothing to undo");
    expect(failingLoad).toHaveBeenCalledTimes(1);
  });
});
