import { Check, Pencil, CircleSlash, Trash2, ChevronLeft, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import Pill from "./Pill.jsx";
import { SYMBOL_LABELS } from "./Symbols.jsx";
import { STATUS, STATUS_ORDER, SYSTEMS } from "../lib/data.js";

/** Right panel: selected item (spec §5, screen F). Renders the review
 *  progress summary when nothing is selected, or the full item detail
 *  — view, edit form, every live warning as its own four-field card
 *  (never collapsed to one — task-15/16), and, when the last write to
 *  this item was refused, an inline banner naming why and how to
 *  recover, right next to the evidence it concerns (DESIGN.md; task-
 *  16-brief.md §4). */
export default function ItemDetailPanel({
  sel, sheets, currentSheet, edit, onStartEdit, onChangeEdit, onSaveEdit, onCancelEdit,
  onApprove, onReject, onRequestDelete, onShowEvidence, onStep, stepIndex, stepCount,
  itemError, onRefreshItem, onDismissItemError,
  counts, itemsTotal, onNextIssue,
}) {
  const aiReading = currentSheet?.aiReading;
  if (!sel) {
    return (
      <aside className="detail" aria-label="Selected item">
        <div className="detail__scroll">
          <h2>Review progress</h2>
          <div className="progressbar" style={{ margin: "12px 0 8px" }}>
            {STATUS_ORDER.filter((k) => counts[k]).map((k) => (
              <i key={k} style={{ width: (counts[k] / itemsTotal) * 100 + "%", background: STATUS[k].color }} />
            ))}
          </div>
          <p className="value value--muted">{counts.approved} of {itemsTotal} items approved</p>

          {STATUS_ORDER.filter((k) => counts[k]).map((k) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: "1px solid var(--line-1)" }}>
              <Pill status={k} />
              <span className="tabular" style={{ fontSize: 13, fontWeight: 600 }}>{counts[k]}</span>
            </div>
          ))}

          {counts.missing || counts.attention ? (
            <>
              <p className="label">Next recommended issue</p>
              <p className="value value--muted" style={{ marginBottom: 10 }}>
                {counts.missing ? "Missing information blocks approval, so start there." : "Conflicting information needs a decision before export."}
              </p>
              <button className="btn btn--primary btn--block" onClick={onNextIssue}>Open next issue</button>
            </>
          ) : (
            <p className="value" style={{ marginTop: 16, color: "var(--green)", fontWeight: 600 }}>Every item has been reviewed.</p>
          )}

          {aiReading ? (
            <div className="ai-reading">
              <p className="label">Read by AI · {currentSheet?.number}</p>
              <p className="value value--muted">{aiReading.summary}</p>
              <ul className="ai-reading-list">
                {aiReading.devices.map((d, i) => (
                  <li key={i}>
                    <span className="tabular ai-reading-count">{d.count}</span>
                    <span>{d.name}</span>
                  </li>
                ))}
              </ul>
              <p className="value value--muted ai-reading-note">
                What the model read from the drawing itself — cross-check against the counted takeoff.
              </p>
            </div>
          ) : (
            <>
              <p className="label">On this sheet</p>
              <p className="value value--muted">Select a symbol on the drawing to review its details, or press J to step through items.</p>
            </>
          )}
        </div>
      </aside>
    );
  }

  const itemSheet = sheets.find((s) => s.id === sel.sheetId);

  const approveBlockedReason = sel.status === "missing"
    ? "Resolve the scale on this sheet before approving a measured item."
    : sel.rejected
    ? "This item was rejected. Undo the rejection before approving it."
    : null;

  return (
    <aside className="detail" aria-label="Selected item">
      <div className="detail__scroll">
        <div className="detail__head">
          <Pill status={sel.rejected ? "rejected" : sel.status} />
          <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{SYMBOL_LABELS[sel.symbol]}</span>
        </div>

        {itemError && (
          <div className="warncard warncard--missing" role="alert">
            <h4>{itemError.code === "stale_item_version" ? "Someone else changed this item" : "This action couldn't be completed"}</h4>
            <p>{itemError.message}</p>
            <div className="actions" style={{ marginTop: 4 }}>
              {itemError.code === "stale_item_version" ? (
                <button className="btn" onClick={onRefreshItem}><RefreshCw size={13} /> Refresh to see the current value</button>
              ) : (
                <button className="btn" onClick={onDismissItemError}>Dismiss</button>
              )}
            </div>
          </div>
        )}

        {!edit ? (
          <>
            <h2>{sel.name}</h2>
            <p className="value value--muted" style={{ margin: "6px 0 0" }}>{sel.description}</p>

            {sel.aiConfirmed ? (
              <p className="ai-confirmed">✓ Identified by the AI reading of the drawing</p>
            ) : null}

            <p className="label">Quantity</p>
            <p className="qty tabular">
              {sel.quantity.toLocaleString()}
              <small>{sel.unit}</small>
            </p>

            <p className="label">Classification</p>
            <p className="value">{sel.system} — {sel.category}</p>

            <p className="label">Location</p>
            <p className="value">Sheet {itemSheet?.number ?? sel.sheetId} · {itemSheet?.revision}</p>

            <p className="label">Source evidence</p>
            {sel.evidence ? (
              <button className="linkbtn" onClick={() => onShowEvidence(sel)}>
                {sel.evidence.detail}, {sel.evidence.sheet} <ExternalLink size={12} style={{ verticalAlign: -1 }} />
              </button>
            ) : (
              <p className="value value--muted">No evidence recorded for this item.</p>
            )}

            {sel.warnings?.map((w) => (
              <div key={w.id} className={"warncard warncard--" + (sel.status === "missing" ? "missing" : "attention")}>
                <h4>{w.title}</h4>
                <p>{w.found}</p>
                <dl style={{ margin: 0 }}>
                  <dt>Why it matters</dt>
                  <dd>{w.why}</dd>
                  <dt>What to do</dt>
                  <dd>{w.fix}</dd>
                  <dt>Where to look</dt>
                  <dd>{w.where}</dd>
                </dl>
              </div>
            ))}

            {sel.approvedBy && (
              <>
                <p className="label">Approved by</p>
                <p className="value">{sel.approvedBy}</p>
              </>
            )}

            {sel.notes && (
              <>
                <p className="label">Notes</p>
                <p className="value">{sel.notes}</p>
              </>
            )}

            <div className="actions">
              <button className="btn btn--primary" onClick={() => onApprove(sel)} disabled={!!approveBlockedReason}>
                <Check size={14} /> Approve item
              </button>
            </div>
            {approveBlockedReason && (
              <p style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 7 }}>{approveBlockedReason}</p>
            )}
            <div className="actions">
              <button className="btn" onClick={() => onStartEdit(sel)}><Pencil size={13} /> Edit</button>
              <button className="btn" onClick={() => onReject(sel)}><CircleSlash size={13} /> Reject</button>
              <button className="btn" onClick={() => onRequestDelete(sel)}><Trash2 size={13} /></button>
            </div>
          </>
        ) : (
          <>
            <h2>Edit item</h2>
            <p className="label">Symbol</p>
            <select className="field" value={edit.symbol} onChange={(e) => onChangeEdit({ ...edit, symbol: e.target.value })}>
              {Object.entries(SYMBOL_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <p className="label">System</p>
            <select className="field" value={edit.system} onChange={(e) => onChangeEdit({ ...edit, system: e.target.value })}>
              {SYSTEMS.map((s) => <option key={s}>{s}</option>)}
            </select>
            <p className="label">Category</p>
            <input className="field" value={edit.category} onChange={(e) => onChangeEdit({ ...edit, category: e.target.value })} />
            <p className="label">Quantity ({sel.unit})</p>
            <input className="field tabular" type="number" min="0" value={edit.quantity} onChange={(e) => onChangeEdit({ ...edit, quantity: e.target.value })} />
            <p className="label">Notes</p>
            <textarea className="field" rows={3} value={edit.notes} onChange={(e) => onChangeEdit({ ...edit, notes: e.target.value })} placeholder="Anything the next reviewer should know" />
            <div className="actions">
              <button className="btn btn--primary" onClick={() => onSaveEdit(sel)}>Save changes</button>
              <button className="btn" onClick={onCancelEdit}>Cancel</button>
            </div>
          </>
        )}
      </div>
      <div className="detail__nav">
        <button className="iconbtn" onClick={() => onStep(-1)}><ChevronLeft size={14} /> Previous</button>
        <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{stepIndex} of {stepCount}</span>
        <button className="iconbtn" onClick={() => onStep(1)}>Next <ChevronRight size={14} /></button>
      </div>
    </aside>
  );
}
