/* The proposal, shown before anything is written (State 2). */
import { changesLine, approveCount, CUSTOM_LINE, UNKNOWN_COPY } from "./decisionCopy.js";

export default function ProposalCard({ item, proposal, busy, onApprove, onConfirmOnly, onReject, onChangeWording }) {
  if (proposal.intent === "unknown") {
    return (
      <div className="decision-card is-pending" role="group" aria-label="Proposal">
        <p className="value">{UNKNOWN_COPY}</p>
        <div className="actions"><button className="btn" onClick={onChangeWording}>Change wording</button></div>
      </div>
    );
  }
  const n = approveCount(item, proposal);
  if (proposal.intent === "exclude") {
    return (
      <div className="decision-card is-pending" role="group" aria-label="Proposal">
        <p className="decision-card__lead">Reject {n} — {proposal.rejectReason}</p>
        <dl className="decision-kv"><dt>Reason</dt><dd>"{proposal.rejectReason}"</dd></dl>
        <p className="value value--muted">{n > 1 ? `Applies to all ${n}` : "Applies to this item"}</p>
        <div className="actions">
          <button className="btn btn--primary" disabled={busy} onClick={onReject}>Reject {n}</button>
          <button className="btn" onClick={onChangeWording}>Change wording</button>
        </div>
      </div>
    );
  }
  return (
    <div className="decision-card is-pending" role="group" aria-label="Proposal">
      <p className="decision-card__lead">Read as <strong>{proposal.name}</strong></p>
      <dl className="decision-kv">
        <dt>System</dt><dd>{proposal.system} — {proposal.category}</dd>
        <dt>Unit</dt><dd>{proposal.unit}</dd>
        <dt>Schedule</dt><dd>{proposal.scheduleMatch ? `${proposal.scheduleMatch.sheet} · ${proposal.scheduleMatch.line} · matched` : "not found"}</dd>
        <dt>Pricing basis</dt><dd>{proposal.catalogId || proposal.scheduleMatch ? "found" : "needs pricing"}</dd>
      </dl>
      {proposal.source === "typed" ? <p className="value value--muted">{CUSTOM_LINE}</p> : null}
      <p className="value value--muted">{changesLine(item, proposal)}</p>
      <div className="actions">
        <button className="btn btn--primary btn--block" disabled={busy} onClick={onApprove}>Confirm and approve {n}</button>
      </div>
      <div className="actions">
        <button className="btn" disabled={busy} onClick={onConfirmOnly}>Confirm, keep reviewing</button>
        <button className="btn" onClick={onChangeWording}>Change wording</button>
      </div>
    </div>
  );
}
