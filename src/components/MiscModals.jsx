import { useState } from "react";
import { Ruler } from "lucide-react";
import Modal from "./Modal.jsx";
import { evidenceImageUrl } from "../lib/store/api-mapping.js";

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
  const [failed, setFailed] = useState(false);
  const url = evidenceImageUrl(item);
  const showImage = url && !failed;
  return (
    <Modal title="Source evidence" onClose={onClose}>
      {showImage ? (
        <div style={{ border: "1px solid var(--line-2)", borderRadius: 6, background: "var(--sheet)", padding: 8, marginBottom: 12 }}>
          <img
            src={url}
            alt={`Source drawing crop for ${item.name}, ${item.evidence.sheet}`}
            style={{ display: "block", width: "100%", borderRadius: 4 }}
            onError={() => setFailed(true)}
          />
        </div>
      ) : (
        <div style={{ marginBottom: 12 }}>
          <p className="value" style={{ marginBottom: 4 }}>
            {item.evidence.detail}, {item.evidence.sheet}
          </p>
          <p className="value value--muted" style={{ margin: 0 }}>
            No drawing crop was captured for this item.
          </p>
        </div>
      )}
      {showImage ? (
        <p style={{ margin: 0, fontSize: 13.5 }}>
          This is the region of {item.evidence.sheet} the quantity was read from. Opening evidence never leaves your place in the review.
        </p>
      ) : null}
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
