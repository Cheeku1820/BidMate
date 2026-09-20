/* ============================================================
   DecisionArea.jsx — "What is this?" (docs/specs/say-what-it-is.md,
   "The panel"). Three states in one slot: the box, the proposal card,
   the statement of what was done. It owns no data: onResolve asks the
   API what a sentence would change, onApply is the estimator's press.
   The chips fill the box and submit; they never bypass it.
   ============================================================ */
import { useEffect, useRef, useState } from "react";
import ProposalCard from "./ProposalCard.jsx";
import { REJECT_CHIP, EXISTING_CHIP, EMPTY_HELPER, timeShort } from "./decisionCopy.js";

export default function DecisionArea({ item, sheetNumber, onResolve, onApply, onUndo, onSelectItem, alsoMatchingItemId }) {
  const [state, setState] = useState(item.status === "approved" || item.rejected ? "done" : "box");
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [helper, setHelper] = useState("");
  const [done, setDone] = useState(null); // { note, approved, rejected, count, alsoMatching, at }
  const boxRef = useRef(null);
  const cardRef = useRef(null);

  // A new item resets the area; an approved or rejected one opens on the
  // statement. Keyed on id ALONE: the store's snapshot refreshing this same
  // item after this area's own apply flips item.status, and if that were in
  // the dependency list it would wipe the statement, the also-matching line,
  // and the sentence out from under the estimator who just wrote them.
  useEffect(() => {
    setText(""); setProposal(null); setHelper(""); setDone(null);
    setState(item.status === "approved" || item.rejected ? "done" : "box");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id]);

  useEffect(() => {
    if (state === "box") boxRef.current?.focus();
    else if (state === "card") cardRef.current?.focus();
  }, [state, item.id]);

  const readingUsable = item.status === "ready" && item.category !== "Unclassified";

  async function submit(sentence) {
    if (busy) return;
    const s = (sentence ?? text).trim();
    if (!s) {
      if (!readingUsable) { setHelper(EMPTY_HELPER); return; }
      return submit(item.name);
    }
    setHelper(""); setBusy(true);
    try {
      const p = await onResolve(s);
      setText(s); setProposal(p); setState("card");
    } finally { setBusy(false); }
  }

  async function apply(approve) {
    if (busy) return;
    setBusy(true);
    try {
      const res = await onApply(proposal, { approve, note: text });
      if (!res) return; // the panel's error banner explains; stay on the card
      setDone({ note: text, approved: approve, rejected: proposal.intent === "exclude",
                count: proposal.quantity ?? item.quantity, alsoMatching: res.alsoMatching, at: new Date().toISOString(), name: proposal.name });
      setState("done");
    } finally { setBusy(false); }
  }

  // Escape's target: back to the box with the sentence intact. Shared by the
  // card's own Escape handler, "Change wording", and the window-level
  // listener below (so Escape works even when focus isn't on the card).
  function backToBox() { setState("box"); }

  useEffect(() => {
    function onCmd(e) {
      const { type } = e.detail || {};
      if (type === "focus") setState("box");
      if (type === "reject" && state !== "done") submit(REJECT_CHIP);
      if (type === "confirm") {
        if (state === "card" && proposal && proposal.intent !== "unknown") apply(proposal.intent !== "exclude");
        else if (state === "box") submit();
      }
    }
    function onWindowKeyDown(e) {
      if (e.key === "Escape" && state === "card") backToBox();
    }
    window.addEventListener("decision-cmd", onCmd);
    window.addEventListener("keydown", onWindowKeyDown);
    return () => {
      window.removeEventListener("decision-cmd", onCmd);
      window.removeEventListener("keydown", onWindowKeyDown);
    };
  });

  if (state === "done") {
    const rejected = done ? done.rejected : item.rejected;
    const approved = done ? done.approved : item.status === "approved";
    const note = done ? done.note : (item.resolveNote || item.rejectReason || "");
    const at = done ? done.at : item.approvedAt;
    const count = done ? done.count : item.quantity;
    const tone = rejected ? "decision-done--rejected" : approved ? "decision-done--approved" : "decision-done--neutral";
    // Undo doesn't wait on the store to refresh this item back to its prior
    // status — it returns to the box locally, right away, with the sentence
    // that produced this statement so the estimator isn't starting over.
    function handleUndo() {
      onUndo();
      setText(note);
      setState("box");
    }
    return (
      <div className={"decision-done " + tone} role="status">
        <p className="decision-done__lead">
          {rejected ? `✕ You rejected ${count} — "${note}"` : approved ? `✓ You approved ${count} ${item.unit}${at ? " · " + timeShort(at) : ""}` : `You read this as ${done?.name ?? item.name}`}
        </p>
        {!rejected && note ? <p className="value value--muted">From your note: "{note}" · <button className="linkbtn" onClick={handleUndo}>Undo</button> · <button className="linkbtn" onClick={() => setState("box")}>Change</button></p>
                          : <p className="value value--muted"><button className="linkbtn" onClick={handleUndo}>Undo</button></p>}
        {done?.alsoMatching?.count > 0 ? (
          <p className="value">
            {done.alsoMatching.count} more {item.sourceTag} on {done.alsoMatching.sheetNumbers.join(", ")} read the same way —{" "}
            <button className="linkbtn" onClick={() => onSelectItem(alsoMatchingItemId)}>review those next →</button>
          </p>
        ) : null}
      </div>
    );
  }

  if (state === "card" && proposal) {
    return (
      <ProposalCard item={item} proposal={proposal} busy={busy} sheetNumber={sheetNumber} cardRef={cardRef} onEscape={backToBox}
        onApprove={() => apply(true)} onConfirmOnly={() => apply(false)} onReject={() => apply(false)}
        onChangeWording={backToBox} />
    );
  }

  return (
    <div className="decision">
      <label className="label" htmlFor="decision-box">What is this?</label>
      <textarea id="decision-box" ref={boxRef} className="field decision__box" rows={2} value={text}
        onChange={(e) => { setText(e.target.value); setHelper(""); }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
        }} />
      <div className="decision__chips">
        <button type="button" className="chip" onClick={() => submit(item.name)}>{item.name}</button>
        {item.scheduleHint ? <button type="button" className="chip" onClick={() => submit(item.scheduleHint)}>{item.scheduleHint}</button> : null}
        <button type="button" className="chip" onClick={() => submit(REJECT_CHIP)}>{REJECT_CHIP}</button>
        <button type="button" className="chip" onClick={() => submit(EXISTING_CHIP)}>{EXISTING_CHIP}</button>
      </div>
      {helper ? <p className="value value--muted">{helper}</p> : null}
      <div className="actions"><button className="btn btn--primary btn--block" disabled={busy} onClick={() => submit()}>Read this</button></div>
      {item.path ? <p className="value value--muted">Length and unit are edited below.</p> : null}
    </div>
  );
}
