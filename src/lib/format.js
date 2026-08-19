export function timeOf(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function initials(name) {
  return name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

const NOT_SET = "Not set";

/** `bidDueDate` is a calendar date with no time component
 *  ("2026-09-14") -- it has to read as the same date for every viewer
 *  regardless of their timezone, the way a deadline printed on a bid
 *  form would. `new Date(iso)` on a date-only string parses as UTC
 *  midnight per the ECMAScript spec, so formatting that instant in the
 *  viewer's local zone with no `timeZone` override renders it a day
 *  early in every zone behind UTC -- every US timezone, and therefore
 *  this product's whole user base. Anchoring the formatter itself to
 *  UTC keeps the calendar date stable no matter where the browser is.
 *  Shared by ProjectsDashboard.jsx and ProjectOverview.jsx -- do not
 *  fork a second copy, and do not fold this into formatTimestamp below
 *  to "simplify" it, since a timestamp needs the opposite behavior. */
export function formatCalendarDate(iso) {
  if (!iso) return NOT_SET;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** `updatedAt` is a full timestamp ("2026-08-17T18:00:00Z"), an actual
 *  instant rather than a calendar date -- it should render in the
 *  viewer's own local zone, so no `timeZone` override here, on
 *  purpose. */
export function formatTimestamp(iso) {
  if (!iso) return NOT_SET;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
