// The bare "@testing-library/jest-dom" entry point extends the global
// `expect`, which only exists when vitest's `globals` option is on.
// This project's vitest.config keeps globals off (every test file
// imports `expect` from "vitest" explicitly), so the vitest-specific
// entry point is the one that actually wires up the matchers here.
import "@testing-library/jest-dom/vitest";

// @testing-library/react normally auto-registers its own afterEach
// cleanup, but that auto-registration looks for `afterEach` on
// globalThis — which, again, this project doesn't populate, since
// globals stays off. Without this, two tests in the same file that
// both render() leave both trees in the document at once, which is
// what "found multiple elements with role heading" during Step 9 below
// actually turned out to be (not a routing bug).
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
});

// Node 25 ships an experimental global Web Storage that shadows jsdom's
// localStorage and is missing the standard mutators (clear/key/length),
// so every test that relies on `localStorage.clear()` for isolation
// throws "localStorage.clear is not a function" under this runtime --
// the seed store's whole contract suite among them. Install a complete
// in-memory Storage whenever the host's localStorage is absent or
// incomplete, so the suite is deterministic no matter which runtime it
// runs on. Production is unaffected: real browsers provide a full
// Storage, and local-transport.js's probe (setItem/removeItem) captures
// whichever object is live here at module load, which now always has
// the full API. Anchored to globalThis and window as the same instance
// so a test clearing one clears both.
class MemoryStorage {
  #map = new Map();
  get length() {
    return this.#map.size;
  }
  key(i) {
    return Array.from(this.#map.keys())[i] ?? null;
  }
  getItem(k) {
    const key = String(k);
    return this.#map.has(key) ? this.#map.get(key) : null;
  }
  setItem(k, v) {
    this.#map.set(String(k), String(v));
  }
  removeItem(k) {
    this.#map.delete(String(k));
  }
  clear() {
    this.#map.clear();
  }
}

if (typeof globalThis.localStorage === "undefined" || typeof globalThis.localStorage.clear !== "function") {
  const storage = new MemoryStorage();
  for (const target of [globalThis, typeof window !== "undefined" ? window : null]) {
    if (!target) continue;
    try {
      Object.defineProperty(target, "localStorage", { value: storage, configurable: true, writable: true });
    } catch {
      target.localStorage = storage;
    }
  }
}
