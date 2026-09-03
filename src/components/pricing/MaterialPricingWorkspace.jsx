/* ============================================================
   MaterialPricingWorkspace.jsx — the Material Pricing workspace
   (docs/superpowers/specs/2026-08-31-labor-material-pricing-design.md).

   Material rows are not part of the review snapshot useReviewStore polls
   -- Task 9's getMaterialRows/setMaterialPrice are a separate surface, exactly
   the way LaborWorkspace.jsx's getLaborRows/setLaborLine sit outside the
   polled snapshot because a material pricing edit is a pricing fact, not a
   takeoff mutation. So this screen fetches its own rows through
   `store` from useWorkspaceContext() rather than reading them off
   `snapshot`, and refetches after every write rather than waiting on
   the shared poll -- the same pattern LaborWorkspace follows.

   A plain table in this codebase's established style
   (TakeoffSpreadsheet.jsx): tabular numerals on every quantity/cost,
   the shared NONE ("—") mark for a value nothing resolved, inline edit
   on a cell, autosave with no save button. Status renders through the
   same Pill component every other screen uses (never a bespoke color
   here) -- CLAUDE.md's "status is never color alone." The
   precedence-tier label ("Estimated basis," "Company standard," ...)
   renders as its own neutral tag (.pill--neutral, already the
   sanctioned "non-status marker" per styles.css's own comment on that
   class) next to -- never merged into -- the status pill.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Pill from "../Pill.jsx";
import { COLUMNS } from "./pricingColumns.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

export default function MaterialPricingWorkspace() {
  const { store, projectId } = useWorkspaceContext();

  const [rows, setRows] = useState(null); // null = loading
  const [pricingSource, setPricingSource] = useState(null);
  const [pricingNote, setPricingNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .getMaterialRows(projectId)
      .then((result) => {
        setRows(result.rows);
        setPricingSource(result.pricingSource);
        setPricingNote(result.pricingNote);
        // Seed local allowance intent from what the server actually has
        // stored, every load -- otherwise a reload forgets an existing
        // allowance's checkbox and reason, and a later price-only edit
        // would silently revert it to a plain project price and erase
        // why the number was a placeholder.
        setAllowance(
          Object.fromEntries(
            result.rows.map((row) => [row.itemId, { on: row.source === "allowance", reason: row.reason || "" }])
          )
        );
      })
      .catch((err) => setLoadError(err?.message || "Couldn't load material pricing. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  // Per-row allowance intent, itemId -> { on, reason }. Held here rather
  // than on the row because it is what the estimator is *about* to save,
  // not what the store returned -- the row itself carries no allowance
  // flag until a price has been written with one.
  const [allowance, setAllowance] = useState({});

  const setAllowanceField = (itemId, field, value) =>
    setAllowance((prev) => ({ ...prev, [itemId]: { ...prev[itemId], [field]: value } }));

  const editPrice = async (itemId, raw) => {
    if (raw === "" || raw == null) return; // an estimator clearing the field is not a value to save
    const n = Number(raw);
    if (Number.isNaN(n)) return;
    const entry = allowance[itemId];
    const isAllowance = Boolean(entry?.on);
    const reason = (entry?.reason || "").trim();
    // Caught here rather than left to the 422: the backend rejects an
    // allowance with no reason (MaterialPriceUpdateIn), and an estimator
    // reading a total needs to know what a placeholder number is
    // standing in for.
    if (isAllowance && !reason) {
      setSaveError("An allowance needs a reason — say what it's standing in for, so the total can be traced back.");
      return;
    }
    setSaveError(null);
    try {
      await store.setMaterialPrice(itemId, {
        priceOverride: n,
        source: isAllowance ? "allowance" : "project_price",
        reason: isAllowance ? reason : "",
      });
      await load();
    } catch (err) {
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  return (
    <>
      <AppTopBar title="Material pricing" />

      <div className="page">
        <h1 className="page-heading">Material pricing</h1>

        {/* Two different facts, so two independent renders. The basis
            note used to be gated behind the automatic source, which meant
            a project priced from the regional table -- no key configured,
            or any automated attempt that fell back -- wrote the note and
            then never showed it. That is where the branch-wiring
            assumption lives, and it is 27 of 45 items and half the labour
            hours on a real set. */}
        {pricingSource !== "llm" ? (
          <p className="muted">
            This project has no automatic regional price estimate. Set a price directly on each row below, or
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

        {rows === null && !loadError ? <p className="muted">Loading material pricing…</p> : null}

        {rows !== null && !loadError ? (
          rows.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items to price yet.</p>
            </div>
          ) : (
            <div className="takeoff-table-scroll">
              <table className="data-table takeoff-table">
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    {COLUMNS.map((c) => (
                      <th key={c.key} scope="col" style={{ textAlign: c.align }}>
                        {c.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.itemId}>
                      <td>
                        <Pill status={row.status} />
                      </td>
                      {COLUMNS.map((c) => (
                        <td
                          key={c.key}
                          className={c.align === "right" ? "tabular" : undefined}
                          style={{ textAlign: c.align }}
                        >
                          {c.key === "itemName" && row.basisNote ? (
                            <>
                              {c.render(row)}
                              <div className="muted">{row.basisNote}</div>
                            </>
                          ) : c.key === "unitPrice" ? (
                            <>
                              <input
                                key={row.unitPrice}
                                type="number"
                                step="0.01"
                                min="0"
                                aria-label="Unit price"
                                defaultValue={row.unitPrice ?? ""}
                                onBlur={(event) => editPrice(row.itemId, event.target.value)}
                                className="field field--number tabular"
                              />
                              <label className="switch">
                                <input
                                  type="checkbox"
                                  checked={Boolean(allowance[row.itemId]?.on)}
                                  onChange={(event) =>
                                    setAllowanceField(row.itemId, "on", event.target.checked)
                                  }
                                />
                                Mark as allowance
                              </label>
                              {allowance[row.itemId]?.on ? (
                                <>
                                  <label
                                    className="formfield-label"
                                    htmlFor={`allowance-reason-${row.itemId}`}
                                  >
                                    Allowance reason
                                  </label>
                                  <input
                                    id={`allowance-reason-${row.itemId}`}
                                    className="field"
                                    type="text"
                                    value={allowance[row.itemId]?.reason ?? ""}
                                    onChange={(event) =>
                                      setAllowanceField(row.itemId, "reason", event.target.value)
                                    }
                                    // Blurring the reason commits the price already on
                                    // the row, so an estimator who priced first and
                                    // marked it an allowance second does not have to
                                    // retype the number. No save button, same as
                                    // everywhere else in this product.
                                    onBlur={() => editPrice(row.itemId, row.unitPrice)}
                                  />
                                </>
                              ) : null}
                            </>
                          ) : c.key === "sourceLabel" ? (
                            row.sourceLabel ? (
                              <span className="pill pill--neutral">{row.sourceLabel}</span>
                            ) : (
                              c.render(row)
                            )
                          ) : (
                            c.render(row)
                          )}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : null}
      </div>
    </>
  );
}
