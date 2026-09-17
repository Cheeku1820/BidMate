import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
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
});

describe("useReviewStore -- symbol match polling", () => {
  // "Find every one like this" (B3b): startMatch kicks off a search,
  // and while it's pending the hook polls store.getMatch every 2s until
  // the status leaves "pending" -- pinned here with fake timers the way
  // ProcessingStatus.test.jsx's own poll tests are: advanceTimersByTimeAsync
  // inside act(), never RTL's findBy*/waitFor, which wait on the real
  // clock and would hang under a faked one.
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function makeStore(overrides = {}) {
    return {
      getSnapshot: vi.fn().mockResolvedValue(null),
      subscribe: vi.fn(() => () => {}),
      setPresence: vi.fn().mockResolvedValue(),
      ...overrides,
    };
  }

  test("startMatch sets match and polling flips it to found when getMatch resolves so", async () => {
    const pendingMatch = { id: "m1", sheetId: "s1", box: [500, 375, 12, 12], status: "pending", count: 0, matches: [], error: "" };
    const foundMatch = { ...pendingMatch, status: "found", count: 3, matches: [{ x: 1, y: 1 }, { x: 2, y: 2 }, { x: 3, y: 3 }] };

    const store = makeStore({
      createMatch: vi.fn().mockResolvedValue(pendingMatch),
      getMatch: vi.fn().mockResolvedValue(foundMatch),
    });

    const { result } = renderHook(() => useReviewStore(store, { onSignedOut: () => {} }));

    await act(async () => {
      await result.current.startMatch("s1", { x: 500, y: 375, w: 12, h: 12 });
    });

    expect(store.createMatch).toHaveBeenCalledWith("s1", { x: 500, y: 375, w: 12, h: 12 });
    expect(result.current.match).toEqual(pendingMatch);

    await act(() => vi.advanceTimersByTimeAsync(2000));

    expect(store.getMatch).toHaveBeenCalledWith("m1");
    expect(result.current.match).toEqual(foundMatch);
  });

  test("polling stops once the match leaves pending", async () => {
    const pendingMatch = { id: "m1", sheetId: "s1", box: [0, 0, 1, 1], status: "pending", count: 0, matches: [], error: "" };
    const foundMatch = { ...pendingMatch, status: "found", count: 1, matches: [{ x: 1, y: 1 }] };

    const store = makeStore({
      createMatch: vi.fn().mockResolvedValue(pendingMatch),
      getMatch: vi.fn().mockResolvedValue(foundMatch),
    });

    const { result } = renderHook(() => useReviewStore(store, { onSignedOut: () => {} }));

    await act(async () => {
      await result.current.startMatch("s1", { x: 0, y: 0, w: 1, h: 1 });
    });

    await act(() => vi.advanceTimersByTimeAsync(2000));
    expect(result.current.match?.status).toBe("found");

    store.getMatch.mockClear();

    await act(() => vi.advanceTimersByTimeAsync(6000));

    expect(store.getMatch).not.toHaveBeenCalled();
  });

  test("clearMatch resets match to null", async () => {
    const pendingMatch = { id: "m1", sheetId: "s1", box: [0, 0, 1, 1], status: "pending", count: 0, matches: [], error: "" };
    const store = makeStore({ createMatch: vi.fn().mockResolvedValue(pendingMatch) });

    const { result } = renderHook(() => useReviewStore(store, { onSignedOut: () => {} }));

    await act(async () => {
      await result.current.startMatch("s1", { x: 0, y: 0, w: 1, h: 1 });
    });
    expect(result.current.match).toEqual(pendingMatch);

    act(() => result.current.clearMatch());
    expect(result.current.match).toBeNull();
  });
});
