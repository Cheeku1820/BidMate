import { describe, expect, test } from "vitest";
import { rangeFailure, rangeToast, reversedToast } from "./rangeCopy.js";

describe("rangeToast", () => {
  test("names the operation and the counts, singular when one", () => {
    expect(rangeToast("paste", 40, 20)).toBe("Pasted 40 cells on 20 rows");
    expect(rangeToast("fill", 12, 12)).toBe("Filled 12 cells on 12 rows");
    expect(rangeToast("clear", 1, 1)).toBe("Cleared 1 cell on 1 row");
  });
  test("appends the skipped rows and why", () => {
    expect(rangeToast("paste", 38, 19, { skipped: 2, skippedWhy: "an allowance needs a reason" })).toBe(
      "Pasted 38 cells on 19 rows — 2 rows skipped, an allowance needs a reason",
    );
    expect(rangeToast("paste", 3, 3, { skipped: 1, skippedWhy: "an allowance needs a reason" })).toBe(
      "Pasted 3 cells on 3 rows — 1 row skipped, an allowance needs a reason",
    );
  });
});

test("rangeFailure and reversedToast", () => {
  expect(rangeFailure(3, 40)).toBe("3 of 40 cells couldn't be saved. Try again.");
  expect(rangeFailure(1, 1)).toBe("1 of 1 cell couldn't be saved. Try again.");
  expect(reversedToast(40)).toBe("Reversed 40 cells");
  expect(reversedToast(1)).toBe("Reversed 1 cell");
});
