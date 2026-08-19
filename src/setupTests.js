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
