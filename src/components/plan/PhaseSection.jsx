/* ============================================================
   PhaseSection.jsx — the phasing the documents call for, and the
   phases the estimator states.

   A detected phase is one line per label across the whole set, with
   every place it appeared listed under the row. An added phase is one
   the documents don't state -- the Gerber case, where the split came
   from the GC's bid instructions -- marked "Stated by you", with Remove.
   Stream D turns confirmed phases into the phase model; here they stop
   at names.
   ============================================================ */

import { useState } from "react";
import PlanLine, { Cite } from "./PlanLine.jsx";
import PlanSection from "./PlanSection.jsx";

const ADD_FAILED = "Couldn't add that phase. Try again.";

export default function PhaseSection({ phases, onDecide, onAdd, onRemove }) {
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const add = () => {
    const cleaned = name.trim();
    if (!cleaned) return;
    setSaving(true);
    setError("");
    onAdd(cleaned)
      .then(() => {
        setSaving(false);
        setName("");
      })
      .catch((err) => {
        setSaving(false);
        setError(err?.message || ADD_FAILED);
      });
  };

  return (
    <>
      <PlanSection
        id="plan-phases-heading"
        title="Phasing"
        description="Every phase the documents name, and where. Confirm the ones this bid is split by, or add a phase the documents don't state."
        emptyText="The documents do not name any phase."
      >
        {phases.map((p) => (
          <PlanLine
            key={p.key}
            line={p}
            onDecide={(change) => onDecide(p.key, change)}
            onRemove={p.added ? () => onRemove(p.phaseId) : null}
          >
            {p.places.length > 1 ? (
              <ul className="plan-places">
                {p.places.slice(1).map((place, i) => (
                  <li key={i}>
                    <Cite documentId={place.documentId} documentFilename={place.documentFilename} page={place.page} />
                    <span className="muted"> — {place.quote}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </PlanLine>
        ))}
      </PlanSection>
      <form
        className="plan-add-phase"
        onSubmit={(e) => {
          e.preventDefault();
          add();
        }}
      >
        <label className="formfield-label" htmlFor="plan-add-phase-name">
          Phase name
        </label>
        <div className="plan-add-phase__row">
          <input id="plan-add-phase-name" className="field" value={name} disabled={saving} maxLength={100}
                 onChange={(e) => setName(e.target.value)} />
          <button type="submit" className="btn" disabled={saving || !name.trim()}>
            Add phase
          </button>
        </div>
        <p className="scope-row__error" aria-live="polite">
          {error || null}
        </p>
      </form>
    </>
  );
}
