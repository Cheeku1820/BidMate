/* ============================================================
   ScopeSection.jsx — what the documents say the electrical work is,
   settled by a person before the takeoff runs.

   The worker reads every uploaded file and lifts out scope statements:
   what is included, excluded, by others, or an alternate, each quoted
   verbatim from its source page. Nothing here is a takeoff item. A
   statement's status -- found, confirmed, dismissed -- is its own
   vocabulary, the same separation notes keep (CLAUDE.md: "a note's
   status is not an item's status"), so it is drawn with .note-status
   and the --slate/--plum hues, never with Pill.jsx or the four review
   labels. Icon + label carry the status; the hue only reinforces.

   Every decision goes through store.decideScope and the row follows the
   server's answer. A refused decision leaves the row exactly as it was,
   with the failure stated on the row itself, so the estimator is never
   looking at a decision the server never took.

   The quote is document text: it is rendered as data, in a blockquote,
   and nothing here interprets it.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import { Check, Search, X } from "lucide-react";

const KIND_ORDER = ["included", "excluded", "by_others", "alternate"];
const KIND_LABELS = { included: "Included", excluded: "Excluded", by_others: "By others", alternate: "Alternates" };

// A scope statement's own words. Deliberately not the four review
// labels: "Confirmed" here means a person agrees the documents say
// this, not that anything in the takeoff is approved.
const STATUS = {
  found: { label: "Found", Icon: Search },
  confirmed: { label: "Confirmed", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
};

const DECIDE_FAILED = "Couldn't save that decision. Try again.";

function ScopeStatus({ status }) {
  const { label, Icon } = STATUS[status] ?? STATUS.found;
  return (
    <span className={`note-status note-status--${status}`}>
      <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
      {label}
    </span>
  );
}

function plural(n, word) {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

function ScopeRow({ statement, onDecide }) {
  const [showSource, setShowSource] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const current = statement.editedText ?? statement.text;
  const edited = statement.editedText != null && statement.editedText !== statement.text;

  const decide = (change) => {
    setSaving(true);
    setError("");
    return onDecide(statement.id, change)
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

  const startEdit = () => {
    setDraft(current);
    setEditing(true);
  };

  const save = () => {
    decide({ editedText: draft }).then((ok) => {
      if (ok) setEditing(false);
    });
  };

  const textareaId = `scope-text-${statement.id}`;
  const errorId = `scope-error-${statement.id}`;

  return (
    <li className="scope-row">
      <div className="scope-row__head">
        <ScopeStatus status={statement.status} />
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
          {edited ? <p className="scope-row__original muted">Original: {statement.text}</p> : null}
          <div className="scope-row__actions">
            {statement.status !== "confirmed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "confirmed" })}>
                Confirm
              </button>
            ) : null}
            <button type="button" className="btn" disabled={saving} onClick={startEdit}>
              Edit
            </button>
            {statement.status !== "dismissed" ? (
              <button type="button" className="btn" disabled={saving} onClick={() => decide({ status: "dismissed" })}>
                Dismiss
              </button>
            ) : null}
            <button
              type="button"
              className="btn"
              aria-expanded={showSource}
              onClick={() => setShowSource((v) => !v)}
            >
              View source
            </button>
          </div>
        </>
      )}

      {/* The source is shown on demand: the verbatim quote, as data, and
          the page it came from, so the estimator can open the document
          to the right place rather than hunt for it. */}
      {showSource ? (
        <figure className="scope-row__source">
          <blockquote className="scope-row__quote">{statement.quote}</blockquote>
          <figcaption className="scope-row__cite tabular">{`${statement.documentFilename}, page ${statement.page}`}</figcaption>
        </figure>
      ) : null}

      {/* Always in the flow so the live region exists before it has
          anything to announce; empty, it takes no height. */}
      <p id={errorId} className="scope-row__error" aria-live="polite">
        {error || null}
      </p>
    </li>
  );
}

export default function ScopeSection({ store, projectId }) {
  const [statements, setStatements] = useState(null);
  const [state, setState] = useState("loading"); // loading | loaded | failed

  // Sticks at false once unmounted, re-armed in the effect body itself
  // so StrictMode's simulated remount doesn't leave it false for good
  // (same guard ConfirmDrawings uses).
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    setState("loading");
    store
      .listScope(projectId)
      .then((rows) => {
        if (!aliveRef.current) return;
        setStatements(rows);
        setState("loaded");
      })
      .catch(() => {
        if (!aliveRef.current) return;
        setState("failed");
      });
  }, [store, projectId]);

  const decide = (id, change) =>
    store.decideScope(id, change).then((updated) => {
      if (aliveRef.current) setStatements((prev) => prev.map((s) => (s.id === id ? updated : s)));
      return updated;
    });

  let body;
  if (state === "loading") {
    body = <p className="muted scope-state">Loading scope statements…</p>;
  } else if (state === "failed") {
    body = (
      <p className="scope-state scope-state--failed" role="alert">
        Couldn't load the scope statements. Check the connection and try again.
      </p>
    );
  } else if (statements.length === 0) {
    body = <p className="muted scope-state">No scope statements were found in the documents.</p>;
  } else {
    const confirmed = statements.filter((s) => s.status === "confirmed").length;
    const dismissed = statements.filter((s) => s.status === "dismissed").length;
    const groups = KIND_ORDER.map((kind) => ({ kind, rows: statements.filter((s) => s.kind === kind) })).filter(
      (g) => g.rows.length > 0
    );
    body = (
      <>
        <p className="scope-summary tabular">
          {plural(statements.length, "statement")} found · {confirmed} confirmed · {dismissed} dismissed
        </p>
        {groups.map((g) => (
          <div key={g.kind} className="scope-group">
            <h3 className="scope-group__title">{KIND_LABELS[g.kind]}</h3>
            <ul className="scope-list">
              {g.rows.map((s) => (
                <ScopeRow key={s.id} statement={s} onDecide={decide} />
              ))}
            </ul>
          </div>
        ))}
      </>
    );
  }

  return (
    <section className="scope-card" aria-labelledby="scope-heading">
      <header className="scope-head">
        <h2 id="scope-heading">Scope stated in the documents</h2>
        <p className="muted">
          What the documents say the electrical work includes and leaves out, quoted from the page it came from. Confirm
          each one, correct its wording, or dismiss it.
        </p>
      </header>
      {body}
    </section>
  );
}
