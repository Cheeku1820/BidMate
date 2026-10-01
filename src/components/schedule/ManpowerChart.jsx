/* ============================================================
   ManpowerChart.jsx — people on site per week, by role.

   This is the chart a GC actually asks a sub for, and it is the same
   numbers the bars above carry, summed per week by the API. Inline SVG
   with class-based fills so it prints and themes with everything else;
   a visually-hidden table mirrors it for anyone reading by ear.
   ============================================================ */

import { COPY } from "./scheduleCopy.js";
import { ROLES } from "./stages.js";

const HEIGHT = 120;
const COLUMN = 28;

export default function ManpowerChart({ schedule }) {
  const weeks = schedule.manpower;
  if (!weeks.length) return null;

  const peak = Math.max(1, schedule.peakCrew);
  const peakWeek = schedule.peakWeek || weeks[0].week;
  const width = weeks.length * COLUMN + 8;
  const summary = COPY.peakAverage(schedule.peakCrew, peakWeek, schedule.averageCrew);

  return (
    <section className="manpower" aria-label="Manpower by week">
      <p className="tabular">{summary}</p>
      <svg
        role="img"
        aria-label={`Manpower by week. ${summary}`}
        viewBox={`0 0 ${width} ${HEIGHT + 16}`}
        className="manpower__svg"
      >
        {weeks.map((week, index) => {
          let y = HEIGHT;
          return (
            <g key={week.week} transform={`translate(${index * COLUMN + 4},0)`}>
              {ROLES.map((role) => {
                const height = (week[role.key] / peak) * HEIGHT;
                y -= height;
                return (
                  <rect
                    key={role.key}
                    className={`manpower__bar manpower__bar--${role.key}`}
                    x={2}
                    y={y}
                    width={COLUMN - 4}
                    height={height}
                  />
                );
              })}
              <text x={COLUMN / 2} y={HEIGHT + 12} textAnchor="middle" className="manpower__week tabular">
                {week.week}
              </text>
            </g>
          );
        })}
      </svg>
      <table className="sr-only">
        <caption>Manpower by week</caption>
        <thead>
          <tr>
            <th scope="col">Week</th>
            {ROLES.map((role) => <th key={role.key} scope="col">{role.label}</th>)}
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week.week}>
              <td>{week.week}</td>
              {ROLES.map((role) => <td key={role.key}>{week[role.key]}</td>)}
              <td>{week.crew}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
