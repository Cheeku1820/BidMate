/* ============================================================
   DecisionArea.jsx — "What is this?" (docs/specs/say-what-it-is.md,
   "The panel"). Three states in one slot: the box, the proposal card,
   the statement of what was done. It owns no data: onResolve asks the
   API what a sentence would change, onApply is the estimator's press.
   The chips fill the box and submit; they never bypass it.
   ============================================================ */
import { useEffect, useRef, useState } from "react";
import ProposalCard from "./ProposalCard.jsx";
import { REJECT_CHIP, EXISTING_CHIP, EMPTY_HELPER, RESOLVE_ERROR, isUnclassified, timeShort } from "./decisionCopy.js";

export default function DecisionArea({ item, sheetNumber, onResolve, onApply, onUndo, onSelectItem, alsoMatchingItemId }) {
  const [state, setState] = useState(item.status === "approved" || item.rejected ? "done" : "box");
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [helper, setHelper] = useState("");
  const [done, setDone] = useState(null); // { note, approved, rejected, count, alsoMatching, at }
  const boxRef = useRef(null);
  const cardRef = useRef(null);
  // The item this render is for. Each async call captures it on the way
  // out and compares on the way back: a resolve or apply that lands after
  // the estimator has J-stepped to another item is discarded, never
  // rendered under the new item's name (A's proposal card on B, or a
  // green "You approved" on a B that is not approved).
  const idRef = useRef(item.id);
  idRef.current = item.id;

  // A new item resets the area; a refresh of the SAME item reconciles
  // instead. These used to be two effects on different deps — but when
  // item.id changes in the same commit as status/rejected (approve A
  // locally, then select an already-rejected B), both ran against the SAME
  // pre-reset closure: the id-reset effect queued the reset for B, then the
  // reconciliation effect below evaluated "contradicted" using A's stale
  // local "done" against B's status/rejected, and its own setState("box")
  // landed after the reset's setState("done") in the same batch — winning.
  // One effect, gated on a ref rather than a second dependency list,
  // removes the ordering dependency instead of papering over it.
  const prevIdRef = useRef(item.id);
  useEffect(() => {
    if (prevIdRef.current !== item.id) {
      prevIdRef.current = item.id;
      setText(""); setProposal(null); setHelper(""); setDone(null); setBusy(false);
      setState(item.status === "approved" || item.rejected ? "done" : "box");
      return;
    }
    // Same item: a refresh that CONTRADICTS what this area shows — the top
    // bar's Ctrl+Z, or a teammate acting on the same item — reconciles
    // rather than being ignored. Green must never linger on an item that
    // is not, in fact, Estimator approved:
    //   - a local "done" the item no longer bears out is dropped, back to
    //     the box, keeping the sentence so nothing is lost;
    //   - with no local "done", an item-derived statement (opened at mount)
    //     follows the same rule and returns to the box if the item stops
    //     being approved/rejected;
    //   - with no local "done" and idle on the box, a fresh approval/
    //     rejection that appears (a teammate's action) opens on it.
    // A refresh that instead CONFIRMS a local apply (status becomes
    // "approved" after approve: true) changes nothing here. State "card"
    // is left alone either way — a pending proposal isn't reconciled
    // mid-edit.
    if (done) {
      const contradicted = (done.approved && item.status !== "approved") || (done.rejected && !item.rejected);
      if (contradicted) { setDone(null); setState("box"); }
      return;
    }
    const itemDone = item.status === "approved" || item.rejected;
    if (state === "done" && !itemDone) setState("box");
    else if (state === "box" && itemDone) setState("done");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, item.status, item.rejected]);

  // The box takes focus by itself only on an unclassified item — the one
  // case where typing is the next thing to do. On every other item it
  // renders unfocused, so J/K/A/E/R and the zoom keys work single-press
  // (the workspace suppresses them while a text field has focus); E, or
  // coming back to the box from the card or the statement, asks for
  // focus explicitly through `focusBoxRef`.
  const focusBoxRef = useRef(false);
  function openBox() {
    focusBoxRef.current = true;
    if (state === "box") boxRef.current?.focus();
    else setState("box");
  }
  const focusedForRef = useRef(null);
  useEffect(() => {
    if (state === "box") {
      if (focusBoxRef.current || isUnclassified(item)) boxRef.current?.focus();
      // The textarea is one DOM node across selections, so focus taken
      // for item A would otherwise ride along to a classified item B.
      else if (focusedForRef.current !== item.id && document.activeElement === boxRef.current) boxRef.current.blur();
      focusedForRef.current = item.id;
      focusBoxRef.current = false;
    } else if (state === "card") cardRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const startedFor = item.id;
    try {
      const p = await onResolve(s);
      if (startedFor !== idRef.current) return; // a different item is selected now; the reset already ran
      setText(s); setProposal(p); setState("card");
    } catch {
      // A failed read leaves the box as it was, with a line that says
      // what to do — never a silent no-op or a stuck busy button.
      if (startedFor !== idRef.current) return;
      setHelper(RESOLVE_ERROR);
    } finally {
      if (startedFor === idRef.current) setBusy(false);
    }
  }

  async function apply(approve) {
    if (busy) return;
    setBusy(true);
    const startedFor = item.id;
    try {
      const res = await onApply(proposal, { approve, note: text });
      if (startedFor !== idRef.current) return; // the write landed on the item it was for; this area shows another
      if (!res) return; // the panel's error banner explains; stay on the card
      setDone({ note: text, approved: approve, rejected: proposal.intent === "exclude",
                count: proposal.quantity ?? item.quantity, alsoMatching: res.alsoMatching, at: new Date().toISOString(), name: proposal.name });
      setState("done");
    } catch {
      // The store surfaces the refusal in the panel's banner; stay on
      // the card so the estimator can press again or change wording.
    } finally {
      if (startedFor === idRef.current) setBusy(false);
    }
  }

  // Escape's target from the card, and "Change wording": normally back to
  // the box with the sentence intact. But if the item has become approved
  // or rejected while the card sat open (a teammate acted on it), there is
  // no sentence left to resume — open on the item-derived statement
  // instead of a box that would just bounce back on the next reconcile.
  // Shared by the card's own Escape handler and the window-level listener
  // below (so Escape works even when focus isn't on the card — the card's
  // own handler stops propagation, so the window branch only ever fires
  // when focus was elsewhere).
  function backToBox() {
    if (item.status === "approved" || item.rejected) setState("done");
    else openBox();
  }

  useEffect(() => {
    function onCmd(e) {
      const { type } = e.detail || {};
      if (type === "focus") openBox();
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
    // Undo is the shared undo, and it reverses whatever is at the head of
    // the stack. That is this statement's own action only when the
    // statement is local to this mount (`done` set by this component's
    // apply). An item-derived statement — an item approved or rejected
    // earlier, by anyone, selected now — offers only Change: its Undo
    // would reverse some unrelated action and then show the box on an
    // item that is still Estimator approved.
    const undoBtn = done ? <button className="linkbtn" onClick={handleUndo}>Undo</button> : null;
    const changeBtn = <button className="linkbtn" onClick={openBox}>Change</button>;
    return (
      <div className={"decision-done " + tone} role="status">
        <p className="decision-done__lead">
          {rejected ? `✕ You rejected ${count} — "${note}"` : approved ? `✓ You approved ${count} ${item.unit}${at ? " · " + timeShort(at) : ""}` : `You read this as ${done?.name ?? item.name}`}
        </p>
        {!rejected && note ? <p className="value value--muted">From your note: "{note}" · {undoBtn}{undoBtn ? " · " : null}{changeBtn}</p>
                          : <p className="value value--muted">{undoBtn ?? changeBtn}</p>}
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
        <button type="button" className="decision__chip" onClick={() => submit(item.name)}>{item.name}</button>
        {item.scheduleHint ? <button type="button" className="decision__chip" onClick={() => submit(item.scheduleHint)}>{item.scheduleHint}</button> : null}
        <button type="button" className="decision__chip" onClick={() => submit(REJECT_CHIP)}>{REJECT_CHIP}</button>
        <button type="button" className="decision__chip" onClick={() => submit(EXISTING_CHIP)}>{EXISTING_CHIP}</button>
      </div>
      {helper ? <p className="value value--muted">{helper}</p> : null}
      <div className="actions"><button className="btn btn--primary btn--block" disabled={busy} onClick={() => submit()}>Read this</button></div>
      {item.path ? <p className="value value--muted">Length and unit are edited below.</p> : null}
    </div>
  );
}
