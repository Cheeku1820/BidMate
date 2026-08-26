import { ArrowLeft, Undo2, Redo2, HelpCircle } from "lucide-react";
import Pill from "./Pill.jsx";
import { timeOf, initials } from "../lib/format.js";

/** The persistent top bar (spec §5, screen F): back, project title and
 *  active set, the overall review-status pill, save state, presence,
 *  undo/redo, help, and Finish review. */
export default function TopBar({
  overall,
  saved,
  me,
  presence,
  undoState,
  onUndo,
  onRedo,
  onHelp,
  onFinish,
  // The active project's name and revision set. Defaulted to the fixture
  // project's own values so the blueprint workspace reads correctly even
  // before the project row loads (and for the fixture itself); a sampled
  // demo project passes its own name here, so the title never shows a
  // different project's name than the one being reviewed.
  title = "Meridian Distribution Center — Division 26",
  subtitle = "Active set: E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1",
}) {
  const avatars = [me, ...presence].slice(0, 5);

  // DESIGN.md, "Undo semantics": "The undo button's tooltip names the
  // action about to be reversed, including who performed it" — undoBy
  // comes straight off the snapshot now, so the tooltip can actually say
  // it rather than naming only the action.
  const undoTitle = undoState.canUndo
    ? `Undo: ${undoState.undoLabel}${undoState.undoBy ? ` (${undoState.undoBy})` : ""}`
    : "Nothing to undo";

  return (
    <header className="topbar">
      <button className="iconbtn"><ArrowLeft size={16} /> Projects</button>
      <div className="topbar__rule" />
      <div className="topbar__title">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <Pill status={overall} />
      <span className="savestate tabular">
        {saved.state === "saving" ? "Saving…" : saved.state === "error" ? "Couldn't save — retrying" : "Saved " + timeOf(saved.at)}
      </span>
      <div className="spacer" />
      <div className="presence">
        {avatars.map((p) => (
          <span key={p.id ?? p.userId} className="avatar" style={{ background: p.color }} title={p.name + (p === me ? " (you)" : "")}>
            {initials(p.name)}
          </span>
        ))}
      </div>
      <div className="topbar__rule" />
      <button className="iconbtn" onClick={onUndo} disabled={!undoState.canUndo} title={undoTitle}>
        <Undo2 size={16} />
      </button>
      <button className="iconbtn" onClick={onRedo} disabled={!undoState.canRedo} title={undoState.canRedo ? `Redo: ${undoState.redoLabel}` : "Nothing to redo"}>
        <Redo2 size={16} />
      </button>
      <button className="iconbtn" onClick={onHelp}><HelpCircle size={16} /></button>
      <button className="btn btn--primary" onClick={onFinish}>Finish review</button>
    </header>
  );
}
