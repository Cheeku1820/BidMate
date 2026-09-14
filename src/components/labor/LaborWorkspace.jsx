/* ============================================================
   LaborWorkspace.jsx — the Labor workspace
   (docs/superpowers/specs/2026-08-31-labor-material-pricing-design.md).

   Labor rows are not part of the review snapshot useReviewStore polls
   -- Task 9's getLaborRows/setLaborLine are a separate surface, exactly
   the way NotesWorkspace.jsx's listNotes/createNote sit outside the
   polled snapshot because a labor edit is a pricing fact, not a
   takeoff mutation. So this screen fetches its own rows through
   `store` from useWorkspaceContext() rather than reading them off
   `snapshot`, and refetches after every write rather than waiting on
   the shared poll -- the same pattern NotesWorkspace's load()/useEffect
   follow.

   A plain table in this codebase's established style
   (TakeoffSpreadsheet.jsx): tabular numerals on every quantity/cost,
   the shared NONE ("—") mark for a value nothing resolved, inline edit
   on a cell, autosave with no save button. Status renders through the
   same Pill component every other screen uses (never a bespoke color
   here) -- CLAUDE.md's "status is never color alone." The
   precedence-tier label ("Estimated basis," "Company standard," ...)
   renders as its own neutral tag (.pill--neutral, already the
   sanctioned "non-status marker" per styles.css's own comment on that
   class) next to -- never merged into -- the status pill, per the
   design doc's "the precedence-tier label renders as its own tag,
   styled distinctly from the four-label status pill."
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Pill from "../Pill.jsx";
import { COLUMNS } from "./laborColumns.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

export default function LaborWorkspace() {
  const { store, projectId } = useWorkspaceContext();

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

  const editHours = async (itemId, raw) => {
    if (raw === "") return; // an estimator clearing the field is not a value to save
    const n = Number(raw);
    if (Number.isNaN(n)) return;
    setSaveError(null);
    try {
      await store.setLaborLine(itemId, { hoursOverride: n });
      await load();
    } catch (err) {
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  // Rate is a second, independently-resolved precedence chain -- an
  // estimator can have hours from a company standard and still need to
  // enter the rate by hand. Without this the screen's own copy ("Set
  // hours and rates directly on each row below") is only half true, and
  // on any project the pricing assistant did not price, every labor row
  // is stuck at Missing information with no in-product remedy.
  const editRate = async (itemId, raw) => {
    if (raw === "") return; // an estimator clearing the field is not a value to save
    const n = Number(raw);
    if (Number.isNaN(n)) return;
    setSaveError(null);
    try {
      await store.setLaborLine(itemId, { rateOverride: n });
      await load();
    } catch (err) {
      setSaveError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  return (
    <>
      <AppTopBar title="Labor" />

      <div className="page">
        <h1 className="page-heading">Labor</h1>

        {/* Two different facts, so two independent renders. The basis
            note used to be gated behind the automatic source, which meant
            a project priced from the regional table -- no key configured,
            or any automated attempt that fell back -- wrote the note and
            then never showed it. That is where the branch-wiring
            assumption lives, and it is 27 of 45 items and half the labour
            hours on a real set. */}
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
                          ) : c.key === "hoursPerUnit" ? (
                            <input
                              // Keyed on the fetched value so a reload after a save (or a
                              // Try again after an error) remounts the field with the fresh
                              // figure -- defaultValue only applies on mount, and an
                              // uncontrolled input would otherwise keep showing whatever was
                              // last typed even after the store returns something else.
                              key={row.hoursPerUnit}
                              type="number"
                              step="0.01"
                              min="0"
                              aria-label="Hours per unit"
                              defaultValue={row.hoursPerUnit ?? ""}
                              onBlur={(event) => editHours(row.itemId, event.target.value)}
                              className="field field--number tabular"
                            />
                          ) : c.key === "rate" ? (
                            <input
                              key={row.rate}
                              type="number"
                              step="0.01"
                              min="0"
                              aria-label="Rate"
                              defaultValue={row.rate ?? ""}
                              onBlur={(event) => editRate(row.itemId, event.target.value)}
                              className="field field--number tabular"
                            />
                          ) : c.key === "hoursSourceLabel" ? (
                            row.hoursSourceLabel ? (
                              <span className="pill pill--neutral">{row.hoursSourceLabel}</span>
                            ) : (
                              c.render(row)
                            )
                          ) : c.key === "rateSourceLabel" ? (
                            row.rateSourceLabel ? (
                              <span className="pill pill--neutral">{row.rateSourceLabel}</span>
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
