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

// The one fallback string for an absent value across the projects
// screens (final-review fix 5) -- ProjectsDashboard.jsx and
// ProjectOverview.jsx previously each carried their own copy ("Not
// set" here, a second local "Not set" in ProjectsDashboard.jsx, and
// "Not assigned" for just the estimator field in ProjectOverview.jsx),
// which is how the same absent-estimator fact ends up reading two
// different ways depending which screen an estimator happens to be on.
// Exported so both screens hold exactly one copy instead of three.
export const NOT_SET = "Not set";

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

/** Whole days from today until a calendar date, or null when there is no
 *  date to count to. Anchored to UTC for the same reason
 *  formatCalendarDate is: `bidDueDate` is a date with no time component,
 *  and a viewer west of UTC must not see a bid deadline slip a day.
 *  Negative means the date has passed; 0 means today. */
function daysUntil(iso) {
  if (!iso) return null;
  const due = new Date(iso);
  if (Number.isNaN(due.getTime())) return null;
  const now = new Date();
  const todayUtc = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  const dueUtc = Date.UTC(due.getUTCFullYear(), due.getUTCMonth(), due.getUTCDate());
  return Math.round((dueUtc - todayUtc) / 86400000);
}

/** The bid-deadline chip's copy and urgency, as one derived value so the
 *  sidebar never states a deadline the date doesn't support. `tone` is
 *  "overdue" | "urgent" | "normal"; it drives hue, and the label carries
 *  the same fact in words so the chip is never colour alone
 *  (CLAUDE.md). */
export function bidDueChip(iso) {
  const days = daysUntil(iso);
  if (days === null) return null;
  if (days < 0) {
    const n = Math.abs(days);
    return { tone: "overdue", label: n === 1 ? "Due 1 day ago" : `Due ${n} days ago` };
  }
  if (days === 0) return { tone: "urgent", label: "Due today" };
  if (days === 1) return { tone: "urgent", label: "Due in 1 day" };
  return { tone: days <= 7 ? "urgent" : "normal", label: `Due in ${days} days` };
}
