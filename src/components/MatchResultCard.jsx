import { useState } from "react";
import { SYMBOL_LABELS } from "./Symbols.jsx";
import { SYSTEMS } from "../lib/vocabulary.js";
import * as copy from "../lib/matchCopy.js";

/** What a drawn box found (B3b spec §8). Not an item yet -- nothing is
 *  counted until the estimator names it or says they are not sure --
 *  so this card carries no review label and no status colour. */
export default function MatchResultCard({ match, onAccept, onDiscard, onRetry, sheetNumber }) {
  const [name, setName] = useState("");
  const [symbol, setSymbol] = useState("receptacle");
  const [system, setSystem] = useState(SYSTEMS[0]);
  const n = match.count;

  if (match.status === "pending") {
    return (
      <section className="matchcard" aria-label="Symbol search">
        <p className="label">Find like this · {sheetNumber}</p>
        <p className="value value--muted">{copy.SEARCHING}</p>
        <button className="btn btn--block" onClick={onDiscard}>Discard</button>
      </section>
    );
  }
  if (match.status === "failed") {
    return (
      <section className="matchcard" aria-label="Symbol search">
        <p className="label">Find like this · {sheetNumber}</p>
        <p className="value">{match.error}</p>
        <button className="btn btn--primary btn--block" onClick={onRetry}>Try again</button>
        <button className="btn btn--block" onClick={onDiscard}>Discard</button>
      </section>
    );
  }
  return (
    <section className="matchcard" aria-label="Symbol search">
      <p className="label">Find like this · {sheetNumber}</p>
      <h2 className="tabular">{copy.found(n)}</h2>
      {n <= 1 && <p className="value value--muted">{copy.NONE_FOUND}</p>}
      {match.error && <p className="value">{match.error}</p>}
      <label className="label" htmlFor="match-name">Name</label>
      <input id="match-name" className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="What is this symbol" />
      <label className="label" htmlFor="match-symbol">Symbol</label>
      <select id="match-symbol" className="field" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
        {Object.entries(SYMBOL_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
      </select>
      <label className="label" htmlFor="match-system">System</label>
      <select id="match-system" className="field" value={system} onChange={(e) => setSystem(e.target.value)}>
        {SYSTEMS.map((s) => <option key={s}>{s}</option>)}
      </select>
      <button className="btn btn--primary btn--block" disabled={!name.trim()} onClick={() => onAccept({ name: name.trim(), symbol, system })}>
        {copy.addLabel(n)}
      </button>
      <button className="btn btn--block" onClick={() => onAccept({ notSure: true })}>{copy.NOT_SURE}</button>
      <button className="btn btn--block" onClick={onDiscard}>Discard</button>
    </section>
  );
}
