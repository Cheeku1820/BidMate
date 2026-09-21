/* ============================================================
   PlanLine.jsx — one line of the project plan.

   Scope statements and every derived line (spec section, schedule,
   phase) share this row, so the words and controls are the same on
   every one: a status in the note-status vocabulary (found, confirmed,
   dismissed -- never the four review labels, never Pill.jsx), the text
   as found or as corrected with the original beneath it, the page it
   came from as a link into the document, the verbatim source on
   demand, and Confirm / Correct / Dismiss / Reopen.

   Every decision goes through `onDecide` and the row follows its
   caller's answer. A refused decision leaves the row exactly as it was,
   with the failure stated on the row, so the estimator is never looking
   at a decision the server never took. The quote is document text: it
   is rendered as data, in a blockquote, and nothing here interprets it.
   ============================================================ */

import { useState } from "react";
import { Check, ExternalLink, RotateCcw, Search, X } from "lucide-react";
import { documentPageHref } from "./pageLink.js";

const STATUS = {
  found: { label: "Found", Icon: Search },
  confirmed: { label: "Confirmed", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
};

export const DECIDE_FAILED = "Couldn't save that decision. Try again.";

export function LineStatus({ status }) {
  const { label, Icon } = STATUS[status] ?? STATUS.found;
  return (
    <span className={`note-status note-status--${status}`}>
      <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
      {label}
    </span>
  );
}

/** "E-set.pdf, page 2" with a link, or "Spec.pdf" alone, or nothing. */
export function Cite({ documentId, documentFilename, page }) {
  if (!documentFilename) return null;
  const href = documentPageHref(documentId, page);
  const text = page ? `${documentFilename}, page ${page}` : documentFilename;
  return (
    <span className="plan-cite tabular">
      {text}
      {href ? (
        <a className="plan-cite__link" href={href} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={12} aria-hidden="true" />
          {page ? "Open page" : "Open document"}
        </a>
      ) : null}
    </span>
  );
}

export default function PlanLine({ line, onDecide, onRemove = null, children = null }) {
  const [showSource, setShowSource] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const current = line.editedText ?? line.text;
  const edited = line.editedText != null && line.editedText !== line.text;
  const id = line.key ?? line.id;

  const run = (promise) => {
    setSaving(true);
    setError("");
    return promise
      .then(() => {
        setSaving(false);
        return true;
      })
      .catch(() => {
        setSaving(false);
        setError(DECIDE_FAILED);
        return false;
      });
  };
  const decide = (change) => run(onDecide(change));

  const save = () => {
    decide({ editedText: draft }).then((ok) => {
      if (ok) setEditing(false);
    });
  };

  const textareaId = `plan-text-${id}`;

  return (
    <li className="scope-row plan-line">
      <div className="scope-row__head">
        <LineStatus status={line.status} />
        {line.added ? <span className="plan-line__stated">Stated by you</span> : null}
        <Cite documentId={line.documentId} documentFilename={line.documentFilename} page={line.page} />
      </div>

      {editing ? (
        <div className="scope-row__edit">
          <label className="formfield-label" htmlFor={textareaId}>
            Statement
          </label>
          <textarea
            id={textareaId}
            className="field scope-row__textarea"
            rows={3}
            value={draft}
            disabled={saving}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="scope-row__actions">
            <button type="button" className="btn btn--primary" disabled={saving || !draft.trim()} onClick={save}>
              Save
            </button>
            <button type="button" className="btn" disabled={saving} onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className="scope-row__text">{current}</p>
          {edited ? <p className="scope-row__original muted">Original: {line.text}</p> : null}
          {children}
          <div className="scope-row__actions">
            {line.status !== "confirmed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "confirmed" })}>
                Confirm
              </button>
            ) : null}
            <button type="button" className="btn" disabled={saving} onClick={() => { setDraft(current); setEditing(true); }}>
              Correct
            </button>
            {line.status !== "dismissed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "dismissed" })}>
                Dismiss
              </button>
            ) : null}
            {line.status !== "found" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "found" })}>
                <RotateCcw size={14} aria-hidden="true" />
                Reopen
              </button>
            ) : null}
            {onRemove ? (
              <button type="button" className="btn" disabled={saving} onClick={() => run(onRemove())}>
                Remove
              </button>
            ) : null}
            {line.quote ? (
              <button type="button" className="btn" aria-expanded={showSource} onClick={() => setShowSource((v) => !v)}>
                View source
              </button>
            ) : null}
          </div>
        </>
      )}

      {showSource && line.quote ? (
        <figure className="scope-row__source">
          <blockquote className="scope-row__quote">{line.quote}</blockquote>
        </figure>
      ) : null}

      <p className="scope-row__error" aria-live="polite">
        {error || null}
      </p>
    </li>
  );
}
