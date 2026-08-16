import { Ruler } from "lucide-react";
import Modal from "./Modal.jsx";
import { SymbolGlyph } from "./Symbols.jsx";
import { STATUS } from "../lib/data.js";
import { displayStatus } from "./Pill.jsx";

/** The remaining, smaller dialogs (spec §5, screen F) — kept together
 *  rather than one file each, unlike FinishReviewModal.jsx: none of
 *  these carries the blocking/acknowledgment logic that earns Finish
 *  review its own file, and each is a handful of lines wrapping
 *  Modal.jsx. */

export function ScaleModal({ sheet, onApplyScale, onCalibrate, onClose }) {
  return (
    <Modal title={sheet.scale === "none" ? "Set drawing scale" : "Confirm drawing scale"} onClose={onClose}>
      <p style={{ margin: "0 0 12px", fontSize: 13.5, color: "var(--ink-2)" }}>
        {sheet.number} — choosing a scale recalculates every measured item on this sheet and clears the related warnings.
      </p>
      {sheet.scaleOptions.map((s) => (
        <button key={s} className="btn btn--block" style={{ justifyContent: "flex-start", marginBottom: 8 }} onClick={() => onApplyScale(s)}>{s}</button>
      ))}
      <button className="btn btn--block" style={{ justifyContent: "flex-start" }} onClick={onCalibrate}>
        <Ruler size={14} /> Calibrate against a known dimension instead
      </button>
    </Modal>
  );
}

export function EvidenceModal({ item, onClose }) {
  const status = displayStatus(item);
  return (
    <Modal title="Source evidence" onClose={onClose}>
      <div style={{ border: "1px solid var(--line-2)", borderRadius: 6, background: "var(--sheet)", padding: 14, marginBottom: 12 }}>
        <svg viewBox="0 0 320 150" width="100%" height="150">
          <rect x="8" y="8" width="304" height="134" fill="#fdfcf9" stroke="#b8b3a9" />
          <line x1="8" y1="42" x2="312" y2="42" stroke="#cfcbc0" />
          <text x="18" y="30" fontSize="11" fill="#5f5b54" fontWeight="700">{item.evidence.sheet} — {item.evidence.detail}</text>
          <g transform="translate(160 95)">
            <SymbolGlyph kind={item.symbol} color={STATUS[status].color} />
          </g>
          <rect x="120" y="60" width="80" height="70" fill="none" stroke={STATUS[status].color} strokeWidth="1.6" strokeDasharray="5 4" />
        </svg>
      </div>
      <p style={{ margin: 0, fontSize: 13.5 }}>
        This is the region of {item.evidence.sheet} the quantity was read from. Opening evidence never leaves your place in the review.
      </p>
    </Modal>
  );
}

export function DeleteModal({ item, onConfirm, onClose }) {
  return (
    <Modal
      title="Delete item"
      onClose={onClose}
      foot={
        <>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn--danger" onClick={() => onConfirm(item)}>Delete item</button>
        </>
      }
    >
      <p style={{ margin: 0, fontSize: 13.5 }}>This removes the item from the takeoff and from every total. You can undo it afterward, and other reviewers will see the change.</p>
    </Modal>
  );
}

const SHORTCUTS = [
  ["A", "Approve the selected item"],
  ["E", "Edit the selected item"],
  ["R", "Reject the selected item"],
  ["J / K", "Next / previous item"],
  ["+ / −", "Zoom in / out"],
  ["0", "Fit page"],
  ["Ctrl or ⌘ Z", "Undo"],
  ["⇧ Ctrl or ⌘ Z", "Redo"],
  ["Esc", "Close this dialog"],
];

export function HelpModal({ onClose }) {
  return (
    <Modal title="Keyboard shortcuts" onClose={onClose}>
      {SHORTCUTS.map(([k, l]) => (
        <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", fontSize: 13.5 }}>
          <span className="kbd">{k}</span>
          <span style={{ color: "var(--ink-2)" }}>{l}</span>
        </div>
      ))}
      <p style={{ fontSize: 12.5, color: "var(--ink-3)", marginBottom: 0 }}>Single-key shortcuts stay off while you are typing in a field.</p>
    </Modal>
  );
}

export function DoneModal({ approvedCount, approvedUnits, onClose }) {
  return (
    <Modal title="Review complete" onClose={onClose} foot={<button className="btn btn--primary" onClick={onClose}>Back to workspace</button>}>
      <p style={{ marginTop: 0, fontSize: 13.5 }}>
        {approvedCount} approved items totalling {approvedUnits.toLocaleString()} units are ready for export preview. In the full product this hands off to screen H.
      </p>
    </Modal>
  );
}
