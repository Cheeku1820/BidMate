/* ============================================================
   ProposalCard.jsx — what would change, where it lands, and the two
   controls.

   It renders and reports. Every write goes through the record's own
   endpoint (applyProposal.js maps kind to store call); this component
   never touches a store. `onApply` / `onDismiss` are reported to the
   caller, which owns the actual commit and the life-cycle status that
   comes back from it.

   A card's words are its own vocabulary — offered, applied, dismissed,
   stale — never the four review labels (Pill.jsx, .pill--*), same
   separation notes already keep from an item's status.
   ============================================================ */

import { useState } from "react";
import { Check, ClipboardList, RotateCcw, X } from "lucide-react";

const STATUS = {
  offered: { label: "Offered", Icon: ClipboardList },
  applied: { label: "Applied", Icon: Check },
  dismissed: { label: "Dismissed", Icon: X },
  stale: { label: "Stale", Icon: RotateCcw },
};

const STALE_SENTENCE = "The records this pointed at have moved on since it was offered.";

function ProposalStatus({ status }) {
  const entry = STATUS[status] ?? STATUS.offered;
  const { label, Icon } = entry;
  return (
    <span className={`note-status note-status--${status}`}>
      <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
      {label}
    </span>
  );
}

function ItemDetails({ proposal }) {
  return (
    <>
      {proposal.targetsPreview?.length ? (
        <ul className="proposal-card__targets">
          {proposal.targetsPreview.map((t, i) => (
            <li key={i} className="proposal-card__target">
              <span>{t.label}</span>
              <span className="tabular">{t.detail}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {proposal.moreCount > 0 ? <p className="proposal-card__more">+{proposal.moreCount} more</p> : null}
      {proposal.note ? <p className="proposal-card__note">{proposal.note}</p> : null}
    </>
  );
}

function NoteDetails({ proposal }) {
  return (
    <>
      <p className="proposal-card__target">{proposal.title}</p>
      <p>{proposal.body}</p>
    </>
  );
}

function ScopeOrPlanLineDetails({ proposal }) {
  if (proposal.status) return <p className="proposal-card__note">{proposal.status}</p>;
  return (
    <>
      {proposal.currentText ? <p className="proposal-card__was">{proposal.currentText}</p> : null}
      <p>{proposal.editedText}</p>
    </>
  );
}

function PlanAnswerDetails({ proposal }) {
  return (
    <>
      {proposal.questionTitle ? <p className="proposal-card__target">{proposal.questionTitle}</p> : null}
      <p>{proposal.body}</p>
    </>
  );
}

function Details({ proposal }) {
  switch (proposal.kind) {
    case "item":
      return <ItemDetails proposal={proposal} />;
    case "note":
      return <NoteDetails proposal={proposal} />;
    case "scope":
    case "plan_line":
      return <ScopeOrPlanLineDetails proposal={proposal} />;
    case "plan_answer":
      return <PlanAnswerDetails proposal={proposal} />;
    default:
      return null;
  }
}

export default function ProposalCard({ proposal, status, onApply, onDismiss }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const canAct = status === "offered" && proposal.kind !== "refused";

  const run = (fn) => {
    setBusy(true);
    setError("");
    Promise.resolve(fn())
      .catch((err) => {
        if (typeof err?.code === "string" && err.message) setError(err.message);
      })
      .finally(() => setBusy(false));
  };

  const handleApply = () => run(onApply);
  const handleDismiss = () => run(onDismiss);

  return (
    <section className="proposal-card">
      {proposal.kind !== "refused" ? <ProposalStatus status={status} /> : null}
      <p className="proposal-card__summary">{proposal.summary}</p>
      <Details proposal={proposal} />

      {status === "stale" ? <p className="proposal-card__note">{STALE_SENTENCE}</p> : null}

      {canAct ? (
        <div className="proposal-card__actions">
          <button type="button" className="btn btn--primary" disabled={busy} onClick={handleApply}>
            {busy ? "Applying…" : "Apply"}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={handleDismiss}>
            Dismiss
          </button>
        </div>
      ) : null}

      <p className="proposal-card__error" aria-live="polite">
        {error || null}
      </p>
    </section>
  );
}
