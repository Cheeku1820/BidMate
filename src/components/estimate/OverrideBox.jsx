/* ============================================================
   OverrideBox.jsx — "I know this one."

   The product assumed a ceiling height at 14 feet; the estimator has
   been in the building. Typing 16 here replaces the number, names them
   on the line so a reader can ask them about it, and lands in the
   action log as one undoable action.

   Deliberately not an approval. There is no approval on a ROM — this
   corrects a number, it does not make anybody answerable for the
   document. The copy says "Enter the value", never "Confirm".

   A scope exclusion gets no box: scope is changed by stating the scope,
   and a typed number there would be an exclusion whose text says one
   thing and whose value says another. The API refuses it too
   (api/app/estimate/override.py); this is the matching client-side
   feedback, not the rule.
   ============================================================ */

import { useState } from "react";
import { COPY } from "./estimateCopy.js";

export default function OverrideBox({ line, onOverride }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(line.value || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  if (line.basis === "standard_exclusion") return null;

  async function submit(event) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    const ok = await onOverride(line, value);
    setSaving(false);
    if (ok) setOpen(false);
    else setError(COPY.overrideError);
  }

  if (!open) {
    return (
      <button type="button" className="est-override-open" onClick={() => setOpen(true)}>
        {/* "Change this" once it is already the estimator's, so a typo
            has a way back. An entered line reads as counted and used to
            lose this control entirely, which left no correction path on
            this screen at all. */}
        {line.source === "estimator" ? COPY.overrideEdit : COPY.overrideOpen}
      </button>
    );
  }

  const fieldId = `est-override-${line.id}`;
  return (
    <form className="est-override" onSubmit={submit}>
      <label className="est-override-label" htmlFor={fieldId}>
        {COPY.overrideLabel}
        {line.unit ? ` (${line.unit})` : ""}
      </label>
      <input
        id={fieldId}
        className="est-override-input"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        maxLength={100}
        autoFocus
      />
      <button type="submit" className="btn btn-primary est-override-save" disabled={saving || !value.trim()}>
        {saving ? COPY.overrideSaving : COPY.overrideSave}
      </button>
      <button type="button" className="btn est-override-cancel" onClick={() => setOpen(false)}>
        {COPY.overrideCancel}
      </button>
      {error && (
        <p className="est-override-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
