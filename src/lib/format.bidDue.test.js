/* ============================================================
   format.bidDue.test.js — the bid-deadline chip's date arithmetic.

   `bidDueDate` is a calendar date with no time component, and the whole
   reason formatCalendarDate anchors itself to UTC is that
   `new Date("2026-09-14")` is UTC midnight: counting the days to it with
   a local-time "today" reads a day early in every timezone behind UTC,
   which is every timezone this product's users are in. A deadline that
   is off by one is worse than no deadline at all, so the arithmetic is
   pinned here rather than trusted.
   ============================================================ */

import { afterEach, describe, expect, it, vi } from "vitest";
import { bidDueChip } from "./format.js";

/** Freezes "now" at a moment late in the US day, which is the case that
 *  breaks a local-time implementation: it is already the next day in UTC. */
function freezeAt(iso) {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(iso));
}

afterEach(() => vi.useRealTimers());

describe("bidDueChip", () => {
  it("has nothing to say when no bid date is set", () => {
    expect(bidDueChip(null)).toBeNull();
    expect(bidDueChip(undefined)).toBeNull();
    expect(bidDueChip("")).toBeNull();
  });

  it("ignores a date it cannot read rather than rendering NaN", () => {
    expect(bidDueChip("not a date")).toBeNull();
  });

  it("counts whole calendar days, not elapsed hours", () => {
    freezeAt("2026-08-27T12:00:00Z");
    expect(bidDueChip("2026-09-15")).toEqual({ tone: "normal", label: "Due in 19 days" });
  });

  it("gives the same answer late in a US evening, when UTC is already tomorrow", () => {
    // 2026-08-27 23:30 UTC is still the 27th in UTC but 16:30 in Pacific
    // time; both must count 19 days to the 15th.
    freezeAt("2026-08-27T23:30:00Z");
    expect(bidDueChip("2026-09-15").label).toBe("Due in 19 days");
  });

  it("names today and tomorrow rather than counting them", () => {
    freezeAt("2026-08-27T12:00:00Z");
    expect(bidDueChip("2026-08-27")).toEqual({ tone: "urgent", label: "Due today" });
    expect(bidDueChip("2026-08-28")).toEqual({ tone: "urgent", label: "Due in 1 day" });
  });

  it("treats a week out as urgent and anything further as ordinary", () => {
    freezeAt("2026-08-27T12:00:00Z");
    expect(bidDueChip("2026-09-03").tone).toBe("urgent"); // 7 days
    expect(bidDueChip("2026-09-04").tone).toBe("normal"); // 8 days
  });

  it("says a passed deadline has passed, in words as well as hue", () => {
    freezeAt("2026-08-27T12:00:00Z");
    expect(bidDueChip("2026-08-26")).toEqual({ tone: "overdue", label: "Due 1 day ago" });
    expect(bidDueChip("2026-08-20")).toEqual({ tone: "overdue", label: "Due 7 days ago" });
  });
});
