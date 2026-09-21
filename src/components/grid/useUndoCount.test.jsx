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

  test("reverses every call the last toast stood for, newest first, then says so, then resets", async () => {
    const undo = vi.fn().mockResolvedValue({ performed: true });
    const load = vi.fn().mockResolvedValue(undefined);
    const showToast = vi.fn();
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast }));
    act(() => result.current.remember({ calls: 3, cells: 5 }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(3);
    expect(load).toHaveBeenCalledTimes(1);
    expect(showToast).toHaveBeenCalledWith("Reversed 5 cells");
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(4);
  });

  test("stops when the stack runs dry, and a rejection reaches the caller", async () => {
    const undo = vi.fn().mockResolvedValueOnce({ performed: true }).mockResolvedValueOnce({ performed: false });
    const load = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useUndoCount({ undo, load, showToast: vi.fn() }));
    act(() => result.current.remember({ calls: 4, cells: 4 }));
    await act(() => result.current.undoLast());
    expect(undo).toHaveBeenCalledTimes(2);
    const failing = renderHook(() => useUndoCount({ undo: vi.fn().mockRejectedValue(new Error("Nothing to undo")), load, showToast: vi.fn() }));
    await expect(failing.result.current.undoLast()).rejects.toThrow("Nothing to undo");
  });
});
