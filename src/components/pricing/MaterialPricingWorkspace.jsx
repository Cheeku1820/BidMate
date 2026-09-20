/* ============================================================
   MaterialPricingWorkspace.jsx — the Material pricing workspace on
   the pricing grid (docs/specs/pricing-grid.md, "The two screens →
   Material pricing").

   Same shape as LaborWorkspace.jsx: rows fetched through `store`,
   one row patched from each write's response, save state and the undo
   toast from the review store. What is particular here:

   - Unit price, Basis, and Reason are one entry on the wire. A commit
     on any of them sends all three from the row's current state plus
     the change.
   - An allowance needs a reason, and the API refuses one without. The
     rule is met on the cell: choosing Allowance with an empty Reason
     holds the choice locally (pendingSource), moves to Reason, opens
     its editor with the message, and sends when the reason commits.
     Escape there drops the held choice.
   - Clearing the price removes the whole entry (DELETE) -- an entry
     without a price is not a state the table can hold.
   ============================================================ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import DataGrid from "../grid/DataGrid.jsx";
import { ALLOWANCE_REASON_MESSAGE, COLUMNS, money } from "./pricingColumns.jsx";
import { REFRESHING, REFRESH_BUSY } from "./marketOutcomeCopy.js";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

// Same cadence a market-pricing run polls at as ProcessingStatus.jsx
// polls a takeoff run: a few seconds is fast enough to feel live without
// hammering the API while a job works through every material row.
const MARKET_JOB_POLL_MS = 5000;

function toastFor(key, value, row, updated) {
  if (key === "unitPrice" && value === null) {
    return `Cleared price on ${row.itemName} — ${updated.sourceLabel ? "now " + updated.sourceLabel : "nothing else is set"}`;
  }
  if (key === "source") {
    return value === "allowance" ? `Marked ${row.itemName} as allowance` : `Marked ${row.itemName} as project price`;
  }
  if (key === "reason") return `Set reason on ${row.itemName}`;
  return `Set price to ${money(value)} on ${row.itemName}`;
}

export default function MaterialPricingWorkspace() {
  const { store, projectId, runMutation, showToast, saved, toast, dismissToast, undo } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingNote, setPricingNote] = useState("");
  const [marketJob, setMarketJob] = useState(null); // "queued" | "running" | null
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);
  const grid = useRef(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getMaterialRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingNote(result.pricingNote);
        setMarketJob(result.marketJob ?? null);
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load material pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while a market-pricing run is going, so rows update as they're
  // priced; stop the moment it clears (load() itself reads the next
  // marketJob off the wire) or the screen unmounts. Same shape as
  // ProcessingStatus.jsx's run poll.
  useEffect(() => {
    if (!marketJob) return undefined;
    const interval = setInterval(load, MARKET_JOB_POLL_MS);
    return () => clearInterval(interval);
  }, [marketJob, load]);

  const refresh = async () => {
    const { queued } = await store.refreshMarketEstimates(projectId);
    if (queued) setMarketJob("queued");
    else showToast(REFRESH_BUSY);
  };

  const replaceRow = (itemId, next) =>
    setRows((current) => current.map((r) => (r.itemId === itemId ? next : r)));

  // `restore` names the fields the optimistic update touched; on
  // failure only those go back, on the row as it is now -- not the
  // whole captured row, which would undo a later commit on the same
  // row that has already landed.
  const send = async (row, key, value, request, restore) => {
    setSaveError(null);
    try {
      const updated = await runMutation(request);
      replaceRow(row.itemId, updated);
      showToast(toastFor(key, value, row, updated));
    } catch (err) {
      setRows((cur) =>
        cur.map((r) => {
          if (r.itemId !== row.itemId) return r;
          const back = { ...r, pendingSource: undefined };
          for (const k of restore) back[k] = row[k];
          return back;
        }),
      );
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  const commit = (row, key, value) => {
    if (key === "unitPrice" && value === null) {
      replaceRow(row.itemId, { ...row, unitPrice: null });
      return send(row, key, value, () => store.clearMaterialPrice(row.itemId), ["unitPrice"]);
    }
    const next = {
      priceOverride: key === "unitPrice" ? value : row.unitPrice,
      source: key === "source" ? value : row.pendingSource || row.source || "project_price",
      reason: key === "reason" ? value : row.reason,
    };
    if (next.source === "allowance" && !next.reason.trim()) {
      // Hold the choice, ask for the reason where the estimator is looking.
      replaceRow(row.itemId, { ...row, pendingSource: "allowance" });
      grid.current.openEditor(row.itemId, "reason", { message: ALLOWANCE_REASON_MESSAGE });
      return undefined;
    }
    replaceRow(row.itemId, {
      ...row,
      unitPrice: next.priceOverride,
      source: next.source,
      reason: next.reason,
      pendingSource: undefined,
    });
    const toastKey = row.pendingSource && key === "reason" ? "source" : key;
    const toastValue = toastKey === "source" ? next.source : value;
    return send(row, toastKey, toastValue, () => store.setMaterialPrice(row.itemId, next), ["unitPrice", "source", "reason"]);
  };

  const cancel = (row, key) => {
    if (key === "reason" && row.pendingSource) replaceRow(row.itemId, { ...row, pendingSource: undefined });
  };

  const totals = useMemo(() => {
    if (!rows) return null;
    const priced = rows.filter((r) => r.unitPrice != null);
    return {
      cost: priced.reduce((sum, r) => sum + Number(r.quantity) * Number(r.unitPrice), 0),
      leftOut: rows.length - priced.length,
    };
  }, [rows]);

  const footer = totals ? (
    <tr>
      <td colSpan={COLUMNS.length - 1}>
        Total
        {totals.leftOut > 0 ? (
          <span className="grid-footer-note">
            {totals.leftOut} {totals.leftOut === 1 ? "row" : "rows"} not yet priced {totals.leftOut === 1 ? "is" : "are"} not in this total
          </span>
        ) : null}
      </td>
      <td className="tabular" style={{ textAlign: "right" }}>{money(totals.cost)}</td>
    </tr>
  ) : null;

  return (
    <>
      <AppTopBar title="Material pricing" saveState={saveStateText(saved)} />

      <div className="page page--fill">
        <h1 className="page-heading">Material pricing</h1>

        <div className="page-actions">
          <button type="button" className="btn" onClick={refresh} disabled={!!marketJob}>
            Refresh market estimates
          </button>
        </div>
        {marketJob ? <p className="muted">{REFRESHING}</p> : null}

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

        {rows === null && !loadError ? <p className="muted">Loading material pricing…</p> : null}

        {rows !== null && !loadError ? (
          rows.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items to price yet.</p>
            </div>
          ) : (
            <DataGrid
              ref={grid}
              columns={COLUMNS}
              rows={rows}
              rowKey={(row) => row.itemId}
              rowLabel={(row) => row.itemName}
              onCommit={commit}
              onCancel={cancel}
              footer={footer}
              caption="Material pricing by item"
            />
          )
        ) : null}

        {/* Same placement as Labor: the basis note sits under the grid
            as provenance for the total, not as a banner above it. */}
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
