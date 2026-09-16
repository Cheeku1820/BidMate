import { describe, expect, test, vi } from "vitest";
import { renderHook } from "@testing-library/react";
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
