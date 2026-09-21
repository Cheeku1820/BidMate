/* ============================================================
   QuestionLine.jsx — one thing the documents did not answer.

   Four fields, always: what was found, why it matters, what to check,
   where the evidence lives -- the same shape a warning has (CLAUDE.md),
   rendered with the warncard styles the item panel already uses.
   Answering saves a context note (the plan screen's onAnswer calls the
   store; the note then feeds the next run and lives on Notes &
   assumptions, which is where "See the note" goes). A question's
   status -- found, answered, dismissed -- is its own vocabulary, never
   the four review labels.
   ============================================================ */

import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, HelpCircle, RotateCcw, X } from "lucide-react";
import { DECIDE_FAILED } from "./PlanLine.jsx";

const STATUS = {
  found: { label: "Found", Icon: HelpCircle },
  answered: { label: "Answered", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
};

export default function QuestionLine({ question, onAnswer, onDismiss, onReopen, notesHref }) {
  const [answering, setAnswering] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { label, Icon } = STATUS[question.status] ?? STATUS.found;
  const textareaId = `plan-answer-${question.key}`;

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

  const save = () =>
    run(onAnswer(draft.trim())).then((ok) => {
      if (ok) {
        setAnswering(false);
        setDraft("");
      }
    });

  return (
    <li className="plan-question">
      <div className="warncard warncard--question">
        <div className="scope-row__head">
          <span className={`note-status note-status--${question.status}`}>
            <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
            {label}
          </span>
          {question.documentFilename ? <span className="plan-cite tabular">{question.documentFilename}</span> : null}
        </div>
        <h4>{question.title}</h4>
        <p className="warncard__found">{question.found}</p>
        <p className="warncard__why">{question.why}</p>
        <p className="warncard__fix">{question.fix}</p>
        <p className="warncard__where">{question.where}</p>

        {answering ? (
          <div className="scope-row__edit">
            <label className="formfield-label" htmlFor={textareaId}>
              Your answer
            </label>
            <textarea id={textareaId} className="field scope-row__textarea" rows={3} value={draft} disabled={saving}
                      onChange={(e) => setDraft(e.target.value)} />
            <div className="scope-row__actions">
              <button type="button" className="btn btn--primary" disabled={saving || !draft.trim()} onClick={save}>
                Save answer
              </button>
              <button type="button" className="btn" disabled={saving} onClick={() => setAnswering(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="scope-row__actions">
            {question.status === "found" ? (
              <>
                <button type="button" className="btn btn--primary" disabled={saving} onClick={() => setAnswering(true)}>
                  Answer
                </button>
                <button type="button" className="btn" disabled={saving} onClick={() => run(onDismiss())}>
                  Dismiss
                </button>
              </>
            ) : (
              <>
                {question.status === "answered" ? (
                  <Link className="btn" to={notesHref}>
                    See the note
                  </Link>
                ) : null}
                <button type="button" className="btn" disabled={saving} onClick={() => run(onReopen())}>
                  <RotateCcw size={14} aria-hidden="true" />
                  Reopen
                </button>
              </>
            )}
          </div>
        )}
        <p className="scope-row__error" aria-live="polite">
          {error || null}
        </p>
      </div>
    </li>
  );
}
