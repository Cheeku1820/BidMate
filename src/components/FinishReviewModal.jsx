import Modal from "./Modal.jsx";

/** Selecting Finish review (DESIGN.md, "Finish review blocking"):
 *  Missing information items block completion with no override, no
 *  "proceed anyway" — Needs attention items may carry forward only
 *  behind an explicit acknowledgment naming the consequence. Rejected
 *  items appear in neither list: they are out of scope for the
 *  takeoff entirely (rules.js's countsTowardTotals), not merely
 *  deprioritized. */
export default function FinishReviewModal({ blocking, soft, ack, onAckChange, onGoToItem, onClose, onComplete }) {
  return (
    <Modal
      title="Review summary"
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>Return to review</button>
          <button className="btn btn--primary" disabled={blocking.length > 0 || (soft.length > 0 && !ack)} onClick={onComplete}>
            Complete review
          </button>
        </>
      }
    >
      {blocking.length > 0 && (
        <>
          <p className="label" style={{ color: "var(--red)", marginTop: 0 }}>Must be resolved before finishing</p>
          {blocking.map((i) => (
            <div className="issuerow" key={i.id}>
              <span><strong>{i.name}</strong> · {i.sheetId} — {i.warnings?.[0]?.title}</span>
              <button className="linkbtn" onClick={() => onGoToItem(i)}>Go to item</button>
            </div>
          ))}
        </>
      )}
      {soft.length > 0 && (
        <>
          <p className="label" style={{ color: "var(--amber)" }}>Can remain as acknowledged allowances</p>
          {soft.map((i) => (
            <div className="issuerow" key={i.id}>
              <span><strong>{i.name}</strong> · {i.sheetId} — {i.warnings?.[0]?.title}</span>
              <button className="linkbtn" onClick={() => onGoToItem(i)}>Go to item</button>
            </div>
          ))}
          {blocking.length === 0 && (
            <label className="switch" style={{ marginTop: 10, alignItems: "flex-start" }}>
              <input type="checkbox" checked={ack} onChange={(e) => onAckChange(e.target.checked)} style={{ marginTop: 2 }} />
              <span>I acknowledge these items are unresolved and accept them as allowances in the exported takeoff.</span>
            </label>
          )}
        </>
      )}
      {!blocking.length && !soft.length && (
        <p style={{ margin: 0, fontSize: 14, color: "var(--green)", fontWeight: 600 }}>Every item has been reviewed. This takeoff is ready to export.</p>
      )}
    </Modal>
  );
}
