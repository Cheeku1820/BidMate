/* ============================================================
   ProjectsFilters.test.jsx — the dashboard's search, filter, and sort
   controls.

   ProjectsDashboard.test.jsx already covers what filtering and sorting
   *do* to the rows. This file covers the controls themselves, and one
   rule that is invisible from the dashboard's side: every field carries
   a persistent visible label. Placeholder-as-label is the usual way that
   breaks, and it fails WCAG 2.2 AA the moment the field has a value —
   the placeholder disappears and the field is left unnamed.

   The filter keys are also asserted against projectStage.js's own
   predicate rather than a list restated here. A chip whose key no longer
   matches a predicate silently shows everything, because matchesFilter
   returns true for an unrecognised key.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectsFilters from "./ProjectsFilters.jsx";
import { matchesFilter } from "../../lib/projectStage.js";

const renderFilters = (over = {}) => {
  const props = {
    search: "",
    onSearch: vi.fn(),
    filter: "active",
    onFilter: vi.fn(),
    sort: "updated",
    onSort: vi.fn(),
    ...over,
  };
  return { ...render(<ProjectsFilters {...props} />), props };
};

describe("ProjectsFilters", () => {
  it("gives search and sort persistent visible labels, not placeholders", () => {
    const { container } = renderFilters();

    const search = screen.getByLabelText(/search projects/i);
    const sort = screen.getByLabelText(/sort by/i);

    // getByLabelText alone would be satisfied by aria-label, which is not
    // visible. These must be real <label> elements the estimator can read.
    for (const field of [search, sort]) {
      const label = container.querySelector(`label[for="${field.id}"]`);
      expect(label).toBeTruthy();
      expect(label.textContent.trim()).not.toBe("");
    }
  });

  it("marks the active filter as pressed, so it is not signalled by colour alone", () => {
    renderFilters({ filter: "needsReview" });

    const active = screen.getByRole("button", { name: /needs review/i });
    expect(active).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^active$/i })).toHaveAttribute("aria-pressed", "false");
  });

  it("reports the chosen filter by a key projectStage.js actually recognises", async () => {
    // matchesFilter returns true for an unknown key, so a typo here would
    // silently show every project rather than failing. Feeding each chip's
    // reported key back through the predicate is what catches that.
    const onFilter = vi.fn();
    renderFilters({ onFilter });

    const chips = screen.getAllByRole("button");
    expect(chips.length).toBeGreaterThan(0);

    for (const chip of chips) {
      onFilter.mockClear();
      await userEvent.click(chip);
      expect(onFilter).toHaveBeenCalledTimes(1);

      const key = onFilter.mock.calls[0][0];
      // An archived project is the one case every non-archived filter
      // must reject and the archived filter must accept — so the two
      // answers together prove the key reached a real branch rather than
      // the catch-all.
      const archived = { archivedAt: "2026-07-01T00:00:00Z", stage: "review", itemsTotal: 1, itemsApproved: 0 };
      expect(matchesFilter(archived, key)).toBe(key === "archived");
    }
  });

  it("is a controlled field that reports each change to its owner", async () => {
    // The value lives in ProjectsDashboard, not here, so typing into a
    // field whose `search` prop never moves reports one character at a
    // time -- asserting a whole typed word would be asserting against a
    // component that does not own the state.
    const onSearch = vi.fn();
    const { rerender } = renderFilters({ search: "River", onSearch });

    expect(screen.getByLabelText(/search projects/i)).toHaveValue("River");

    await userEvent.type(screen.getByLabelText(/search projects/i), "s");
    expect(onSearch).toHaveBeenLastCalledWith("Rivers");

    // And it re-renders from the prop, so the owner's state is what the
    // estimator sees.
    rerender(
      <ProjectsFilters
        search="Riverside"
        onSearch={onSearch}
        filter="active"
        onFilter={vi.fn()}
        sort="updated"
        onSort={vi.fn()}
      />,
    );
    expect(screen.getByLabelText(/search projects/i)).toHaveValue("Riverside");
  });
});
