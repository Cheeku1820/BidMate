/* ============================================================
   NoteForm.jsx — add or edit a note, as a form rather than a
   conversation. CLAUDE.md's whole reason this feature exists in this
   shape: "anything sayable in the panel is doable through a form,
   field, or menu" (ROADMAP.md 2.6). This form is that field.

   Every input carries a persistent visible label (no placeholder
   standing in for one), and the `usage` control is a plain labelled
   checkbox rather than a toggle whose state needs a legend to read --
   its own helper text says exactly what checking it does, in
   construction language, with no mention of a re-run "engine" or any
   processing internals.

   `category` has no server-side default (NoteCreateIn requires it), so
   this form seeds a real value on mount rather than leaving a select on
   a blank first option -- a required field an estimator never touched
   should not be able to reach the server unset.
   ============================================================ */

import { useState } from "react";
import Modal from "../Modal.jsx";
import { CATEGORY_LABELS, SCOPE_LABELS } from "./noteVocabulary.js";

const SCOPES = ["project", "company", "sheet", "item"];
const CATEGORIES = Object.keys(CATEGORY_LABELS);

function fieldsFromNote(note) {
  return {
    scope: note?.scope ?? "project",
    title: note?.title ?? "",
    body: note?.body ?? "",
    category: note?.category ?? CATEGORIES[0],
    status: note?.status ?? "open",
    rfiNeeded: note?.rfiNeeded ?? false,
    usage: note?.usage ?? "reference",
    sourceRef: note?.sourceRef ?? "",
    obsoleteAfterRevision: note?.obsoleteAfterRevision ?? "",
  };
}

export default function NoteForm({ note = null, onSave, onClose }) {
  const [values, setValues] = useState(() => fieldsFromNote(note));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const set = (key) => (event) => setValues((v) => ({ ...v, [key]: event.target.value }));

  async function onSubmit(event) {
    event.preventDefault();
    if (!values.title.trim() || !values.body.trim()) {
      setError("Enter a title and the note itself before saving.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave({
        ...values,
        title: values.title.trim(),
        body: values.body.trim(),
      });
    } catch (err) {
      setError(err?.message || "This note couldn't be saved. Try again.");
      setSaving(false);
    }
  }

  return (
    <Modal
      title={note ? "Edit note" : "Add note"}
      onClose={onClose}
      foot={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="note-form" className="btn btn--primary" disabled={saving}>
            {saving ? "Saving…" : "Save note"}
          </button>
        </>
      }
    >
      <form id="note-form" className="form-column" onSubmit={onSubmit} noValidate>
        {error ? (
          <div className="warncard warncard--missing" role="alert">
            <p>{error}</p>
          </div>
        ) : null}

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-title">
            Title
          </label>
          <input
            id="note-title"
            className="field"
            type="text"
            value={values.title}
            onChange={set("title")}
            maxLength={300}
          />
        </div>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-body">
            Note
          </label>
          <p className="formfield-hint" id="note-body-hint">
            What the drawings don't say — an assumption, an exclusion, or an instruction from the customer.
          </p>
          <textarea
            id="note-body"
            className="field"
            rows={4}
            value={values.body}
            onChange={set("body")}
            aria-describedby="note-body-hint"
          />
        </div>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-category">
            Category
          </label>
          <select id="note-category" className="field" value={values.category} onChange={set("category")}>
            {CATEGORIES.map((key) => (
              <option key={key} value={key}>
                {CATEGORY_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-scope">
            Applies to
          </label>
          <select id="note-scope" className="field" value={values.scope} onChange={set("scope")}>
            {SCOPES.map((key) => (
              <option key={key} value={key}>
                {SCOPE_LABELS[key]}
              </option>
            ))}
          </select>
        </div>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-status">
            Status
          </label>
          <select id="note-status" className="field" value={values.status} onChange={set("status")}>
            <option value="open">Open — still needs a decision</option>
            <option value="confirmed">Confirmed — settled and ready to rely on</option>
          </select>
        </div>

        <label className="switch">
          <input
            type="checkbox"
            checked={values.rfiNeeded}
            onChange={(e) => setValues((v) => ({ ...v, rfiNeeded: e.target.checked }))}
          />
          Needs an answer from the customer or architect (RFI)
        </label>

        <label className="switch" aria-describedby="note-usage-hint">
          <input
            type="checkbox"
            checked={values.usage === "context"}
            onChange={(e) => setValues((v) => ({ ...v, usage: e.target.checked ? "context" : "reference" }))}
          />
          Feeds the takeoff
        </label>
        <p className="formfield-hint" id="note-usage-hint">
          Marked this way, the note is used the next time the takeoff is re-run. Otherwise it is kept as
          documentation only.
        </p>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-source-ref">
            Where this comes from
            <span className="formfield-required"> (optional)</span>
          </label>
          <input
            id="note-source-ref"
            className="field"
            type="text"
            placeholder="Spec section, scope letter, or email"
            value={values.sourceRef}
            onChange={set("sourceRef")}
          />
        </div>

        <div className="formfield">
          <label className="formfield-label" htmlFor="note-obsolete-after">
            Clears automatically after revision
            <span className="formfield-required"> (optional)</span>
          </label>
          <input
            id="note-obsolete-after"
            className="field"
            type="text"
            placeholder="e.g. Rev 4"
            value={values.obsoleteAfterRevision}
            onChange={set("obsoleteAfterRevision")}
          />
        </div>
      </form>
    </Modal>
  );
}
