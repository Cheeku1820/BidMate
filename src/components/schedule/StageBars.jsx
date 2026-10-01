/* ============================================================
   StageBars.jsx — one row per phase, one bar per stage, on a week grid.

   Every number a bar shows came from the API: hours, crew, days, dates,
   and the week it sits in. This file positions and labels, and derives
   nothing. Selection is a ring, never a fill; an override reads as the
   "Yours" tier tag, never as a status pill — a stage is not an item.
   ============================================================ */

import { AlertTriangle } from "lucide-react";
import { COPY } from "./scheduleCopy.js";
import { crewText } from "./stages.js";

function shortDate(iso) {
  if (!iso) return "";
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** The grid spans the work, not the procurement.
 *
 *  An order-by date counted back from a 40-week lead falls tens of
 *  weeks before the job starts. Widening the axis to reach it turns the
 *  schedule into a sliver at the right-hand edge — the chart stops
 *  showing the thing it exists to show. Markers outside the span clamp
 *  to its edge instead, and the marker's own note carries the date and
 *  says the order date has passed, so nothing is hidden by the clamp. */
function weekSpan(schedule) {
  const bars = schedule.phases.flatMap((phase) => phase.bars);
  return { first: 1, last: Math.max(1, ...bars.map((bar) => bar.endWeek)) };
}

export default function StageBars({ schedule, selected, onSelect }) {
  const { first, last } = weekSpan(schedule);
  const weeks = [];
  for (let week = first; week <= last; week += 1) weeks.push(week);
  // Column 1 is the phase name; every week after it is one column.
  const column = (week) => week - first + 2;
  const clampWeek = (week) => Math.min(Math.max(week, first), last);
  const weekStart = (week) => schedule.manpower.find((row) => row.week === week)?.start ?? null;

  return (
    <div className="stage-bars" role="group" aria-label="Stage bars by phase">
      <div
        className="stage-bars__grid"
        style={{ gridTemplateColumns: `160px repeat(${weeks.length}, minmax(56px, 1fr))` }}
      >
        <div className="stage-bars__corner" />
        {weeks.map((week) => (
          <div key={week} className="stage-bars__week tabular" style={{ gridColumn: column(week) }}>
            {schedule.relative || !weekStart(week) ? `Week ${week}` : shortDate(weekStart(week))}
          </div>
        ))}

        {(() => {
          // Row allocation: every phase gets one marker row for its
          // order-by dates, then ONE ROW PER BAR. Sharing a row across
          // a phase's stages would stack any two that fall in the same
          // week on top of each other -- sequential work rendered as a
          // single smudge, which is exactly what a schedule must not
          // do. Rows accumulate, so the count is carried between
          // phases rather than derived from the index.
          let nextRow = 2;
          return schedule.phases.map((phase) => {
            const markerRow = nextRow;
            const firstBarRow = markerRow + 1;
            const rowCount = Math.max(1, phase.bars.length);
            nextRow = firstBarRow + rowCount;
            const leads = schedule.leads.filter((lead) => lead.phaseId === phase.id && lead.orderByWeek != null);
            const passed = leads.filter((lead) => lead.passed);
            return [
            ...leads.map((lead) => (
              <span
                key={`marker-${lead.itemId}`}
                role="img"
                className={[
                  "order-marker",
                  lead.stale ? "order-marker--stale" : "",
                  lead.passed ? "order-marker--passed" : "",
                ].filter(Boolean).join(" ")}
                style={{ gridRow: markerRow, gridColumn: column(clampWeek(lead.orderByWeek)) }}
                aria-label={`${COPY.orderBy} ${shortDate(lead.orderBy)}: ${lead.itemName}`}
                title={`${lead.itemName} — ${COPY.orderBy} ${shortDate(lead.orderBy)}`}
              >
                {lead.stale ? <AlertTriangle size={12} aria-hidden="true" /> : null}◆
              </span>
            )),
            ...passed.map((lead) => (
              <span
                key={`note-${lead.itemId}`}
                className="order-marker__note"
                style={{ gridRow: markerRow, gridColumn: `${column(clampWeek(lead.orderByWeek))} / -1` }}
              >
                {lead.itemName}: {lead.note}
              </span>
            )),
            <div
              key={`name-${phase.id}`}
              className="stage-bars__phase"
              style={{ gridRow: `${firstBarRow} / span ${rowCount}`, gridColumn: 1 }}
            >
              {phase.name}
            </div>,
            ...phase.bars.map((bar, barIndex) => {
              const yours = Object.values(bar.sources).some((source) => source === "estimator");
              const isSelected = selected?.phaseId === phase.id && selected?.stage === bar.stage;
              return (
                <button
                  key={`${phase.id}-${bar.stage}`}
                  type="button"
                  className={`stage-bar stage-bar--${bar.stage}${isSelected ? " stage-bar--selected" : ""}`}
                  style={{
                    gridRow: firstBarRow + barIndex,
                    gridColumn: `${column(bar.startWeek)} / ${column(bar.endWeek) + 1}`,
                  }}
                  aria-pressed={Boolean(isSelected)}
                  onClick={() => onSelect({ phaseId: phase.id, stage: bar.stage })}
                  aria-label={`${bar.label} — ${bar.hours} h, ${crewText(bar.crew)}, ${bar.durationDays} days`}
                >
                  <span className="stage-bar__label">{bar.label}</span>
                  <span className="stage-bar__meta tabular">
                    {bar.hours} h · {crewText(bar.crew)} · {bar.durationDays} d
                  </span>
                  {bar.note ? <span className="stage-bar__note">{bar.note}</span> : null}
                  {yours ? <span className="tier-tag">{COPY.yours}</span> : null}
                </button>
              );
            }),
            phase.bars.length === 0 ? (
              <span
                key={`empty-${phase.id}`}
                className="muted"
                style={{ gridRow: firstBarRow, gridColumn: `2 / -1` }}
              >
                {COPY.nothingToSchedule}
              </span>
            ) : null,
            ];
          });
        })()}
      </div>
    </div>
  );
}
