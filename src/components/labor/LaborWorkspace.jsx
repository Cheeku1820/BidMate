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
   ============================================================ */

import { useCallback, useEffect, useMemo, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import DataGrid from "../grid/DataGrid.jsx";
import { COLUMNS, FIELDS, money } from "./laborColumns.jsx";
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
  const { store, projectId, runMutation, showToast, saved, toast, dismissToast, undo } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingSource, setPricingSource] = useState(null);
  const [pricingNote, setPricingNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getLaborRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingSource(result.pricingSource);
        setPricingNote(result.pricingNote);
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load labor pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

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
      showToast(toastFor(key, value, row, updated));
    } catch (err) {
      // Only the edited field, on the row as it is now -- not the whole
      // captured row, which would undo a later commit on the same row
      // that has already landed.
      setRows((cur) => cur.map((r) => (r.itemId === row.itemId ? { ...r, [key]: row[key] } : r)));
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
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

        {pricingSource !== "llm" ? (
          <p className="muted">
            This project has no automatic labor-hour estimate. Set hours and rates directly on each row below, or
            reprocess the project once a pricing assistant is configured.
          </p>
        ) : null}
        {pricingNote ? <p className="muted">{pricingNote}</p> : null}

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
              footer={footer}
              caption="Labor by item"
            />
          )
        ) : null}
      </div>

      {toast ? (
        <div className="toast" role="status">
          {toast.text}
          <button
            type="button"
            onClick={() => {
              undo()
                .then(load)
                .catch((err) => setSaveError(err?.message || "That change couldn't be undone. Try again."));
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
