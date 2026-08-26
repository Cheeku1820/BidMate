/* ============================================================
   Accuracy.test.jsx — screen I behaviour: the honest empty state, and
   the rule that no headline accuracy percentage is shown without a
   benchmark set behind it.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Accuracy from "./Accuracy.jsx";

const renderAccuracy = () =>
  render(
    <MemoryRouter>
      <Accuracy />
    </MemoryRouter>,
  );

describe("Accuracy", () => {
  it("names the empty state and what builds the benchmark, without a fabricated percentage", () => {
    renderAccuracy();
    expect(screen.getByText(/no benchmark set yet/i)).toBeTruthy();
    // No headline accuracy number until a benchmark cohort clears the threshold.
    expect(screen.queryByText(/\d+%/)).toBeNull();
  });

  it("keeps the eventual sections legible so the screen's shape is clear", () => {
    renderAccuracy();
    expect(screen.getByText(/count accuracy by category/i)).toBeTruthy();
    expect(screen.getByText(/length variance by system/i)).toBeTruthy();
  });
});
