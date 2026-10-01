/* ============================================================
   PhaseList.jsx — the phases of a job, as rows.

   Nothing about phases shows anywhere until a second one exists: a
   single-phase bid (the FedEx case in the corpus) sees one plain row
   and the Add button, and no phase column on any other screen. The
   controls that only make sense against a choice — reorder, delete,
   sheet assignment — appear with the second phase.
   ============================================================ */

import { useState } from "react";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { COPY } from "./scheduleCopy.js";

function PhaseRow({
  phase, phases, sheets, multi,
  onRename, onDates, onReorder, onDelete, onAssignSheets, onLineHours,
}) {
  const [editingName, setEditingName] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [picked, setPicked] = useState(() => new Set(phase.sheetIds));
  const index = phases.findIndex((p) => p.id === phase.id);
  const neighbour = index > 0 ? phases[index - 1] : phases[1];
  const owned = sheets.filter((sheet) => phase.sheetIds.includes(sheet.id));

  function startAssigning() {
    setPicked(new Set(phase.sheetIds));
    setAssigning(true);
  }

  return (
    <li className="phase-row">
      <div className="phase-row__head">
        {editingName ? (
          <input
            aria-label={COPY.phaseName}
            defaultValue={phase.name}
            autoFocus
            onBlur={(event) => {
              setEditingName(false);
              const next = event.target.value.trim();
              if (next && next !== phase.name) onRename(phase.id, next);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.target.blur();
              if (event.key === "Escape") setEditingName(false);
            }}
          />
        ) : (
          <button type="button" className="phase-row__name" onClick={() => setEditingName(true)}>
            {phase.name}
          </button>
        )}
        <span className="phase-row__hours tabular">
          {COPY.directHours}: {phase.directHours.toFixed(2)}
        </span>
        {multi ? (
          <span className="phase-row__controls">
            <button
              type="button"
              aria-label={`Move ${phase.name} up`}
              disabled={index === 0}
              onClick={() => onReorder(phase.id, index - 1)}
            >
              <ArrowUp size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label={`Move ${phase.name} down`}
              disabled={index === phases.length - 1}
              onClick={() => onReorder(phase.id, index + 1)}
            >
              <ArrowDown size={16} aria-hidden="true" />
            </button>
            <button
              type="button"
              aria-label={`${COPY.deletePhase} ${phase.name}`}
              onClick={() => onDelete(phase.id, neighbour?.name ?? "")}
            >
              <Trash2 size={16} aria-hidden="true" />
            </button>
          </span>
        ) : null}
      </div>

      {multi ? (
        <div className="phase-row__sheets">
          {owned.map((sheet) => (
            <span key={sheet.id} className="pill pill--neutral">{sheet.number}</span>
          ))}
          <button type="button" className="link" onClick={startAssigning}>{COPY.assignSheets}</button>
          {phase.itemsMovedIn ? <span className="muted tabular">{COPY.movedIn(phase.itemsMovedIn)}</span> : null}
          {phase.itemsMovedOut ? <span className="muted tabular">{COPY.movedOut(phase.itemsMovedOut)}</span> : null}
        </div>
      ) : null}

      {assigning ? (
        <fieldset className="phase-row__assign">
          <legend>Sheets in {phase.name}</legend>
          {sheets.map((sheet) => (
            <label key={sheet.id}>
              <input
                type="checkbox"
                checked={picked.has(sheet.id)}
                onChange={(event) => {
                  const next = new Set(picked);
                  if (event.target.checked) next.add(sheet.id);
                  else next.delete(sheet.id);
                  setPicked(next);
                }}
              />
              {sheet.number} {sheet.title}
            </label>
          ))}
          <div className="phase-row__assign-actions">
            <button
              type="button"
              className="btn btn--primary"
              onClick={() => {
                onAssignSheets(phase.id, [...picked]);
                setAssigning(false);
              }}
            >
              {COPY.moveSheets}
            </button>
            <button type="button" className="btn" onClick={() => setAssigning(false)}>{COPY.dismiss}</button>
          </div>
        </fieldset>
      ) : null}

      <div className="phase-row__dates">
        <label>
          {COPY.start}
          <input
            type="date"
            value={phase.startDate ?? ""}
            onChange={(event) => onDates(phase.id, { startDate: event.target.value || null })}
          />
        </label>
        <label>
          {COPY.requiredFinish}
          <input
            type="date"
            value={phase.requiredFinishDate ?? ""}
            onChange={(event) => onDates(phase.id, { requiredFinishDate: event.target.value || null })}
          />
        </label>
      </div>

      <details className="phase-row__lines">
        <summary className="tabular">
          {COPY.generalConditions}: {phase.generalConditionsHours.toFixed(2)} h
        </summary>
        {phase.lines.map((line) => (
          <div key={line.id} className="phase-line">
            <span>{line.label}</span>
            <input
              type="text"
              inputMode="decimal"
              className="tabular"
              aria-label={`${line.label} hours`}
              key={`${line.id}-${line.hours}`}
              defaultValue={line.hours.toFixed(2)}
              onKeyDown={(event) => {
                if (event.key === "Enter") event.target.blur();
              }}
              onBlur={(event) => {
                const raw = event.target.value.trim();
                if (raw === "") {
                  onLineHours(phase.id, line.id, null);
                  return;
                }
                const value = Number(raw);
                if (Number.isFinite(value) && value >= 0 && value !== line.hours) {
                  onLineHours(phase.id, line.id, value);
                }
              }}
            />
            <span className="tier-tag">{line.source === "estimator" ? COPY.yours : COPY.computed}</span>
            {line.source === "estimator" ? (
              <button type="button" className="link" onClick={() => onLineHours(phase.id, line.id, null)}>
                {COPY.resetToComputed}
              </button>
            ) : null}
          </div>
        ))}
      </details>
    </li>
  );
}

export default function PhaseList({
  schedule, sheets, onAddPhase, onPropose, onApplyProposal, ...rowActions
}) {
  const [adding, setAdding] = useState(false);
  const [proposal, setProposal] = useState(null);
  const { phases, multiPhase } = schedule;

  return (
    <section className="phase-list" aria-label="Phases">
      <ul>
        {phases.map((phase) => (
          <PhaseRow
            key={phase.id}
            phase={phase}
            phases={phases}
            sheets={sheets}
            multi={multiPhase}
            {...rowActions}
          />
        ))}
      </ul>

      <div className="phase-list__actions">
        {adding ? (
          <input
            aria-label={COPY.phaseName}
            autoFocus
            placeholder={`Phase ${phases.length + 1}`}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                onAddPhase(event.target.value.trim(), phases[phases.length - 1]?.id ?? null);
                setAdding(false);
              }
              if (event.key === "Escape") setAdding(false);
            }}
          />
        ) : (
          <button type="button" className="btn" onClick={() => setAdding(true)}>{COPY.addPhase}</button>
        )}
        {!multiPhase ? (
          <button
            type="button"
            className="btn"
            onClick={async () => setProposal(await onPropose())}
          >
            {COPY.proposeFromSheets}
          </button>
        ) : null}
      </div>

      {proposal ? (
        <div className="proposal-card" role="group" aria-label="Proposed phases">
          <p>{proposal.note}</p>
          {proposal.phases.length ? (
            <ul className="proposal-card__list">
              {proposal.phases.map((phase) => (
                <li key={phase.name}>
                  <strong>{phase.name}</strong> — {(phase.sheetNumbers ?? phase.sheet_numbers ?? []).join(", ")}
                </li>
              ))}
            </ul>
          ) : null}
          <div className="proposal-card__actions">
            {proposal.phases.length ? (
              <button
                type="button"
                className="btn btn--primary"
                onClick={() => {
                  onApplyProposal(proposal);
                  setProposal(null);
                }}
              >
                {COPY.confirmProposal}
              </button>
            ) : null}
            <button type="button" className="btn" onClick={() => setProposal(null)}>{COPY.dismiss}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
