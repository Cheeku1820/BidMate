/* ============================================================
   StageEditor.jsx — one bar's fields, each with where it came from and
   a way back to computed.

   The window solve is shown, never applied on its own: the crew that
   would meet a required finish is a sentence beside a button, and a
   window tighter than one crew can meet says so instead of proposing
   fourteen electricians.
   ============================================================ */

import { X } from "lucide-react";
import { COPY } from "./scheduleCopy.js";

const FIELDS = [
  { key: "foreman", label: "Foreman", kind: "int", read: (bar) => bar.crew.foreman },
  { key: "journeyman", label: "Journeyman", kind: "int", read: (bar) => bar.crew.journeyman },
  { key: "apprentice", label: "Apprentice", kind: "int", read: (bar) => bar.crew.apprentice },
  {
    key: "productiveHoursPerDay",
    label: "Productive hours per day",
    kind: "decimal",
    source: "productive_hours_per_day",
    read: (bar) => bar.productiveHoursPerDay,
  },
  { key: "hoursOverride", label: "Hours", kind: "decimal", source: "hours", read: (bar) => bar.hours },
  { key: "startDate", label: "Start", kind: "date", source: "start", read: (bar) => bar.start ?? "" },
  {
    key: "durationDays",
    label: "Duration (working days)",
    kind: "int",
    source: "duration_days",
    read: (bar) => bar.durationDays,
  },
];

function shortDate(iso) {
  return iso ? new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
}

export default function StageEditor({ phase, bar, onChange, onClose }) {
  function commit(field, raw) {
    if (raw === "" || raw == null) {
      onChange({ [field.key]: null });
      return;
    }
    if (field.kind === "date") {
      if (raw !== field.read(bar)) onChange({ [field.key]: raw });
      return;
    }
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return;
    if (field.kind === "int" && !Number.isInteger(value)) return;
    if (value !== Number(field.read(bar))) onChange({ [field.key]: value });
  }

  const suggested = bar.neededCrew;
  const journeymenForSuggested =
    suggested == null ? null : Math.max(0, suggested - bar.crew.foreman - bar.crew.apprentice);

  return (
    <aside className="stage-editor" aria-label={`${bar.label} on ${phase.name}`}>
      <header className="stage-editor__head">
        <h3>{bar.label} — {phase.name}</h3>
        <button type="button" aria-label="Close" onClick={onClose}>
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      {FIELDS.map((field) => {
        const source = bar.sources[field.source ?? field.key] ?? "computed";
        const id = `stage-${bar.stage}-${field.key}`;
        return (
          <div key={field.key} className="stage-editor__field">
            <label htmlFor={id}>{field.label}</label>
            <input
              id={id}
              type={field.kind === "date" ? "date" : "text"}
              inputMode={field.kind === "int" ? "numeric" : "decimal"}
              className="tabular"
              key={`${id}-${field.read(bar)}`}
              defaultValue={field.read(bar)}
              onBlur={(event) => commit(field, event.target.value.trim())}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.target.blur();
              }}
            />
            <span className="tier-tag">{source === "estimator" ? COPY.yours : COPY.computed}</span>
            {source === "estimator" ? (
              <button
                type="button"
                className="link"
                aria-label={`Reset ${field.label.toLowerCase()} to computed`}
                onClick={() => onChange({ [field.key]: null })}
              >
                {COPY.resetToComputed}
              </button>
            ) : null}
          </div>
        );
      })}

      {suggested != null && phase.requiredFinishDate ? (
        <div className="stage-editor__solve">
          {bar.overMax ? (
            <p>{bar.overMaxNote}</p>
          ) : (
            <>
              <p>{COPY.toFinishBy(suggested, bar.label, shortDate(phase.requiredFinishDate))}</p>
              <button
                type="button"
                className="btn"
                onClick={() => onChange({ journeyman: journeymenForSuggested })}
              >
                {COPY.applyCrew(suggested)}
              </button>
            </>
          )}
        </div>
      ) : null}
    </aside>
  );
}
