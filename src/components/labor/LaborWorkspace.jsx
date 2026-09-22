/* ============================================================
   LaborWorkspace.jsx — the Labor workspace on the pricing grid
   (docs/specs/pricing-grid.md, "The two screens → Labor").

   Labor rows are not part of the review snapshot useReviewStore polls
   -- getLaborRows/setLaborLine are a separate surface, because a labor
   edit is a pricing fact, not a takeoff mutation. So this screen
   fetches its own rows through `store` from useWorkspaceContext(), and
   after a write replaces the one row the PATCH response describes
   rather than refetching the list (the grid's active cell must not
   lose its place mid-Tab).

   What it borrows from the review store is the reporting: runMutation
   drives the top bar's Saving…/Saved, showToast the five-second Undo.
   Undo pulls from the shared stack and lands in the action log, not in
   this screen's rows, so the toast's Undo reloads them.

   A pasted, filled, or cleared range lands as N sequential
   store.setLaborLine calls -- one PATCH per cell, each its own
   undoable action -- through commitRange below, rather than one
   combined request; see docs/specs/spreadsheet-grid.md, "What the
   screens do with a range". The toast's Undo reverses however many
   calls the operation made, through useUndoCount, so it still reads
   as one press whether it undoes a single cell or a pasted block --
   but only for the toast that count was remembered for. useUndoCount
   is told the toast's own text alongside the count, and the button
   hands back whatever text is on screen when it is pressed, so a
   later toast this screen never remembered (an "Undid …" from
   Ctrl+Z, say) reverses just itself.
   ============================================================ */

import { useCallback, useEffect, useMemo, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import DataGrid from "../grid/DataGrid.jsx";
import { COLUMNS, FIELDS, money } from "./laborColumns.jsx";
import { rangeFailure, rangeToast } from "../grid/rangeCopy.js";
import { useUndoCount } from "../grid/useUndoCount.js";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

const SOURCE_OF = { hoursPerUnit: "hoursSourceLabel", rate: "rateSourceLabel" };

function toastFor(key, value, row, updated) {
  const field = FIELDS[key];
  if (value === null) {
    const source = SOURCE_OF[key] ? updated[SOURCE_OF[key]] : null;
    if (!SOURCE_OF[key]) return `Cleared ${field.noun} on ${row.itemName}`;
    return `Cleared ${field.noun} on ${row.itemName} — ${source ? "now " + source : "nothing else is set"}`;
  }
  if (!field.format) return `Set ${field.noun} on ${row.itemName}`;
  return `Set ${field.noun} to ${field.format(value)} on ${row.itemName}`;
}

export default function LaborWorkspace() {
  const { store, projectId, runMutation, showToast, saved, toast, dismissToast, undo, redo } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingNote, setPricingNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getLaborRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingNote(result.pricingNote);
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load labor pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const undoCount = useUndoCount({ undo, load, showToast });

  const replaceRow = (itemId, next) =>
    setRows((current) => current.map((r) => (r.itemId === itemId ? next : r)));

  // The grid reports one changed cell; this sends it, patches the row
  // from the response, and restores the field on failure. A clear is a
  // null value on the wire for the numeric fields and "" for the
  // reason, which the API normalises the same way.
  const commit = async (row, key, value) => {
    const field = FIELDS[key];
    const wire = key === "adjustmentReason" && value === null ? "" : value;
    replaceRow(row.itemId, { ...row, [key]: value });
    setSaveError(null);
    try {
      const updated = await runMutation(() => store.setLaborLine(row.itemId, { [field.wire]: wire }));
      replaceRow(row.itemId, updated);
      const label = toastFor(key, value, row, updated);
      undoCount.remember({ calls: 1, cells: 1, text: label });
      showToast(label);
    } catch (err) {
      // Only the edited field, on the row as it is now -- not the whole
      // captured row, which would undo a later commit on the same row
      // that has already landed.
      setRows((cur) => cur.map((r) => (r.itemId === row.itemId ? { ...r, [key]: row[key] } : r)));
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  // A range lands as one PATCH per cell, sequentially, each its own
  // action (docs/specs/spreadsheet-grid.md, "What the screens do with a
  // range"). Every change is applied locally first so the footer moves
  // at once; each response replaces its row, keeping any value on that
  // row still waiting to be sent; a failure restores that one cell and
  // the run continues.
  const commitRange = async (changes, { kind }) => {
    setSaveError(null);
    setRows((cur) =>
      cur.map((r) => {
        const mine = changes.filter((c) => c.row.itemId === r.itemId);
        if (!mine.length) return r;
        const next = { ...r };
        for (const c of mine) next[c.key] = c.value;
        return next;
      }),
    );
    let done = 0;
    let failed = 0;
    const touched = new Set();
    for (let i = 0; i < changes.length; i += 1) {
      const c = changes[i];
      const field = FIELDS[c.key];
      const wire = c.key === "adjustmentReason" && c.value === null ? "" : c.value;
      try {
        const updated = await runMutation(() => store.setLaborLine(c.row.itemId, { [field.wire]: wire }));
        const pending = changes.slice(i + 1).filter((p) => p.row.itemId === c.row.itemId);
        const merged = { ...updated };
        for (const p of pending) merged[p.key] = p.value;
        replaceRow(c.row.itemId, merged);
        done += 1;
        touched.add(c.row.itemId);
      } catch {
        setRows((cur) => cur.map((r) => (r.itemId === c.row.itemId ? { ...r, [c.key]: c.row[c.key] } : r)));
        failed += 1;
      }
    }
    if (failed) setSaveError(rangeFailure(failed, changes.length));
    if (done) {
      const label = rangeToast(kind, done, touched.size);
      undoCount.remember({ calls: done, cells: done, text: label });
      showToast(label);
    }
  };

  const totals = useMemo(() => {
    if (!rows) return null;
    const priced = rows.filter((r) => r.adjustedHours != null && r.laborCost != null);
    return {
      hours: priced.reduce((sum, r) => sum + Number(r.adjustedHours), 0),
      cost: priced.reduce((sum, r) => sum + Number(r.laborCost), 0),
      leftOut: rows.length - priced.length,
    };
  }, [rows]);

  const footer = totals ? (
    <tr>
      <td colSpan={COLUMNS.length - 2}>
        Total
        {totals.leftOut > 0 ? (
          <span className="grid-footer-note">
            {totals.leftOut} {totals.leftOut === 1 ? "row" : "rows"} not yet priced {totals.leftOut === 1 ? "is" : "are"} not in this total
          </span>
        ) : null}
      </td>
      <td className="tabular" style={{ textAlign: "right" }}>{totals.hours.toFixed(2)}</td>
      <td className="tabular" style={{ textAlign: "right" }}>{money(totals.cost)}</td>
    </tr>
  ) : null;

  return (
    <>
      <AppTopBar title="Labor" saveState={saveStateText(saved)} />

      <div className="page page--fill">
        <h1 className="page-heading">Labor</h1>

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : null}

        {saveError ? (
          <div className="load-error" role="alert">
            <p>{saveError}</p>
          </div>
        ) : null}

        {rows === null && !loadError ? <p className="muted">Loading labor pricing…</p> : null}

        {rows !== null && !loadError ? (
          rows.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items to price yet.</p>
            </div>
          ) : (
            <DataGrid
              columns={COLUMNS}
              rows={rows}
              rowKey={(row) => row.itemId}
              rowLabel={(row) => row.itemName}
              onCommit={commit}
              onCommitRange={commitRange}
              onUndo={() => undo().then(load).catch((err) => setSaveError(err?.message || "That change couldn't be undone. Try again."))}
              onRedo={() => redo().then(load).catch((err) => setSaveError(err?.message || "That change couldn't be redone. Try again."))}
              footer={footer}
              caption="Labor by item"
            />
          )
        ) : null}

        {/* The basis note travels with the numbers, under them rather
            than as a banner above: it is provenance for the total
            (the 30-ft-per-device wiring rule lives here), not a
            headline. */}
        {rows !== null && !loadError && pricingNote ? (
          <p className="pricing-basis">
            <span className="pricing-basis__label">Pricing basis</span> {pricingNote}
          </p>
        ) : null}
      </div>

      {toast ? (
        <div className="toast" role="status">
          {toast.text}
          <button
            type="button"
            onClick={() => {
              undoCount.undoLast(toast.text).catch((err) => setSaveError(err?.message || "That change couldn't be undone. Try again."));
              dismissToast();
            }}
          >
            Undo
          </button>
        </div>
      ) : null}
    </>
  );
}
