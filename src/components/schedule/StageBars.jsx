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

function weekSpan(schedule) {
  const bars = schedule.phases.flatMap((phase) => phase.bars);
  const orderWeeks = schedule.leads.map((lead) => lead.orderByWeek).filter((week) => week != null);
  const last = Math.max(1, ...bars.map((bar) => bar.endWeek), ...orderWeeks);
  const first = Math.min(1, ...orderWeeks);
  return { first, last };
}

export default function StageBars({ schedule, selected, onSelect }) {
  const { first, last } = weekSpan(schedule);
  const weeks = [];
  for (let week = first; week <= last; week += 1) weeks.push(week);
  // Column 1 is the phase name; every week after it is one column.
  const column = (week) => week - first + 2;
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

        {schedule.phases.map((phase, phaseIndex) => {
          const markerRow = phaseIndex * 2 + 2;
          const barRow = markerRow + 1;
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
                style={{ gridRow: markerRow, gridColumn: column(Math.max(lead.orderByWeek, first)) }}
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
                style={{ gridRow: markerRow, gridColumn: `${column(Math.max(lead.orderByWeek, first))} / -1` }}
              >
                {lead.itemName}: {lead.note}
              </span>
            )),
            <div key={`name-${phase.id}`} className="stage-bars__phase" style={{ gridRow: barRow, gridColumn: 1 }}>
              {phase.name}
            </div>,
            ...phase.bars.map((bar) => {
              const yours = Object.values(bar.sources).some((source) => source === "estimator");
              const isSelected = selected?.phaseId === phase.id && selected?.stage === bar.stage;
              return (
                <button
                  key={`${phase.id}-${bar.stage}`}
                  type="button"
                  className={`stage-bar stage-bar--${bar.stage}${isSelected ? " stage-bar--selected" : ""}`}
                  style={{ gridRow: barRow, gridColumn: `${column(bar.startWeek)} / ${column(bar.endWeek) + 1}` }}
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
                style={{ gridRow: barRow, gridColumn: `2 / -1` }}
              >
                {COPY.nothingToSchedule}
              </span>
            ) : null,
          ];
        })}
      </div>
    </div>
  );
}
