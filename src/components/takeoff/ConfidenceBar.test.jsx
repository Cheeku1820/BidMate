/* Task 12 of docs/plans/estimate-without-asking.md — the 1–10 meter.

   The estimator asked for a bar rather than a digit, which puts the
   whole burden of the text channel on the accessible label. CLAUDE.md
   requires a text alternative for every status channel and forbids
   colour or shape alone, so a bar whose label does not carry the number
   AND its reasons is not a legible control — it is decoration.

   The other rule this file holds: the label never implies a
   probability. "4 out of 10" is a meter; "40% confident" would be a
   figure an estimator could multiply by the total, which is the
   anti-goal the spec names second. */

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ConfidenceBar from "./ConfidenceBar.jsx";

describe("ConfidenceBar", () => {
  it("draws ten steps and fills to the score", () => {
    render(<ConfidenceBar value={3} reasons={["Typical for the other sheets on this job"]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/3 out of 10/i);
  });

  it("names its reasons in the accessible label, since a bar alone is shape only", () => {
    render(<ConfidenceBar value={4} reasons={["Measured on a sheet with no confirmed scale"]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/no confirmed scale/i);
  });

  it("renders empty rather than zero when nothing was scored", () => {
    /* Review focus 5: items predating the column. "Not scored" and "1
       out of 10" are different claims and must not look the same. */
    render(<ConfidenceBar value={null} reasons={[]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/not scored/i);
  });

  it("fills as many steps as the score and no more", () => {
    const { container } = render(<ConfidenceBar value={3} reasons={[]} />);
    expect(container.querySelectorAll(".conf-step")).toHaveLength(10);
    expect(container.querySelectorAll(".conf-step--on")).toHaveLength(3);
  });

  it("fills nothing when there is no score", () => {
    const { container } = render(<ConfidenceBar value={null} reasons={[]} />);
    expect(container.querySelectorAll(".conf-step--on")).toHaveLength(0);
  });

  it("never states a percentage", () => {
    render(<ConfidenceBar value={7} reasons={["Measured against a confirmed scale"]} />);
    const label = screen.getByRole("img").getAttribute("aria-label");
    expect(label).not.toMatch(/%|percent/i);
  });

  it("clamps a value outside the meter rather than drawing past the end", () => {
    const { container } = render(<ConfidenceBar value={14} reasons={[]} />);
    expect(container.querySelectorAll(".conf-step--on")).toHaveLength(10);
  });

  it("says a score of ten means a person checked it", () => {
    /* The one thing the top of the scale means. Without it, 10 reads as
       "the software is very sure", which is the opposite of the point. */
    render(<ConfidenceBar value={10} reasons={["Approved by an estimator"]} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/approved by an estimator/i);
  });
});
