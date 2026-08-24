/* ============================================================
   TakeoffSpreadsheet.jsx — spec §10, screen G, lean scope
   (BUILD-STAGES.md: "flat table, no grouping, but with bulk approve on
   Ready to review" -- bulk approve itself is Task 5).

   Reads the layout's single store subscription and selection through
   useWorkspaceContext() (Task 1) rather than opening a second one --
   the blueprint and this table are two views of one list (DESIGN.md's
   "Blueprint and table synchronization"), and a second subscription
   would give them two independently-polled ideas of what the data is.

   Row selection (click a row, highlight the selected one, scroll it
   into view) reads and writes the layout's shared selectedItemId /
   selectItem() (Task 4) rather than owning a second selection state --
   the blueprint marker and this row are the same one field moving, per
   DESIGN.md's "Blueprint and table synchronization".

   The item-name cell is a <th scope="row">, not a <td> -- it names
   which item the row describes, and a screen-reader user stepping
   cell-to-cell needs that association read out with every other value
   in the row (WCAG 2.2 AA). A scope="row" <th> is exposed to the
   accessibility tree as role "rowheader", not "cell", so it is
   excluded from `within(row).getAllByRole("cell")`; the ruling on
   task-3-report.md's flagged conflict was to fix the test's
   cell-locating line to read the rowheader directly rather than to
   drop the semantic markup -- see TakeoffSpreadsheet.test.jsx's
   "sorts by a column" test and the report's fix-round section.
   ============================================================ */

import { useEffect, useMemo, useRef, useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Pill, { displayStatus } from "../Pill.jsx";
import { STATUS } from "../../lib/data.js";
import { COLUMNS, DEFAULT_VISIBLE } from "./spreadsheetColumns.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";

/* The four review labels, in the order CLAUDE.md's status table lists
   them. `rejected` is a boolean flag folded into display by
   displayStatus(), never a fifth filter chip beside these four --
   that is the exact accident CLAUDE.md warns about. */
const STATUS_FILTER_KEYS = ["ready", "attention", "missing", "approved"];

/* Filter chips show a short visible label with the full status label
   on aria-label (WCAG 2.5.3: the visible text is a substring of the
   accessible name, so voice-control users can still say the full
   phrase). This also keeps a chip's own text from duplicating a
   status Pill's text verbatim -- with both rendered at once, a
   text-content query for "Needs attention" has to resolve to the one
   row that actually carries that status, not also match the control
   used to filter for it. */
const FILTER_SHORT_LABEL = { ready: "Ready", attention: "Attention", missing: "Missing", approved: "Approved" };

/* Columns an estimator cannot hide: status and item name are the
   minimum an estimator needs to tell one row from the next, so their
   checkboxes in the column-visibility list are disabled rather than
   letting a review session accidentally lose both. */
const LOCKED_COLUMNS = new Set(["status", "name"]);

export default function TakeoffSpreadsheet() {
  const { snapshot, loading, loadError, refresh, selectedItemId, selectItem } = useWorkspaceContext();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState(null);
  const [sort, setSort] = useState({ key: null, dir: "asc" });
  const [visible, setVisible] = useState(() => new Set(DEFAULT_VISIBLE));
  const [columnsOpen, setColumnsOpen] = useState(false);

  const selectedRowRef = useRef(null);
  useEffect(() => {
    // Selecting a marker on the canvas has to bring its row into view
    // here, or the two views agree about the selection while showing the
    // estimator different things. scrollIntoView is unimplemented in
    // jsdom (undefined there), hence the optional call.
    selectedRowRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selectedItemId]);

  const sheetsById = useMemo(() => {
    const map = {};
    for (const sheet of snapshot?.sheets ?? []) map[sheet.id] = sheet;
    return map;
  }, [snapshot]);

  const renderCtx = useMemo(() => ({ sheetsById }), [sheetsById]);

  const visibleColumns = useMemo(() => COLUMNS.filter((c) => visible.has(c.key)), [visible]);

  const allItems = snapshot?.items ?? [];

  const rows = useMemo(() => {
    // Rejected is a flag, not a status (CLAUDE.md) -- it is excluded
    // from the default view the same way a superseded sheet is
    // excluded from totals: quietly, by rule, not by a filter chip.
    let result = allItems.filter((item) => !item.rejected);

    if (statusFilter) {
      result = result.filter((item) => item.status === statusFilter);
    }

    const needle = search.trim().toLowerCase();
    if (needle) {
      result = result.filter((item) =>
        [item.name, item.description].filter(Boolean).some((field) => field.toLowerCase().includes(needle)),
      );
    }

    if (sort.key) {
      const column = COLUMNS.find((c) => c.key === sort.key);
      if (column) {
        const withKeys = result.map((item) => ({ item, key: String(column.render(item, renderCtx)) }));
        withKeys.sort((a, b) => a.key.localeCompare(b.key));
        result = withKeys.map((entry) => entry.item);
        if (sort.dir === "desc") result = result.reverse();
      }
    }

    return result;
  }, [allItems, statusFilter, search, sort, renderCtx]);

  const toggleSort = (key) => {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  };

  const toggleColumn = (key) => {
    if (LOCKED_COLUMNS.has(key)) return;
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const clearSearch = () => setSearch("");

  return (
    <>
      <AppTopBar title="Takeoff" />

      <div className="page">
        <h1 className="page-heading">Takeoff spreadsheet</h1>

        {loading ? <p className="muted">Loading takeoff…</p> : null}

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : null}

        {!loading && !loadError ? (
          allItems.length === 0 ? (
            <div className="empty-state">
              <h2>No items yet</h2>
              <p>This project has no takeoff items yet.</p>
            </div>
          ) : (
            <>
              <div className="takeoff-controls">
                <div className="formfield">
                  <label className="formfield-label" htmlFor="takeoff-search">
                    Search items
                  </label>
                  <input
                    id="takeoff-search"
                    className="field"
                    type="search"
                    value={search}
                    placeholder="Item name or description"
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>

                <div className="filter-chips" role="group" aria-label="Filter by status">
                  <button
                    type="button"
                    className="filter-chip"
                    aria-pressed={statusFilter === null}
                    onClick={() => setStatusFilter(null)}
                  >
                    All statuses
                  </button>
                  {STATUS_FILTER_KEYS.map((key) => (
                    <button
                      key={key}
                      type="button"
                      className="filter-chip"
                      aria-pressed={statusFilter === key}
                      aria-label={STATUS[key].label}
                      onClick={() => setStatusFilter(key)}
                    >
                      {FILTER_SHORT_LABEL[key]}
                    </button>
                  ))}
                </div>

                <div className="takeoff-columns-toggle">
                  <button
                    type="button"
                    className="btn"
                    aria-expanded={columnsOpen}
                    onClick={() => setColumnsOpen((open) => !open)}
                  >
                    Columns
                  </button>
                  {columnsOpen ? (
                    <div className="takeoff-columns">
                      {COLUMNS.map((column) => (
                        <label key={column.key} className="switch">
                          <input
                            type="checkbox"
                            checked={visible.has(column.key)}
                            disabled={LOCKED_COLUMNS.has(column.key)}
                            onChange={() => toggleColumn(column.key)}
                          />
                          {column.label}
                        </label>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>

              {rows.length === 0 ? (
                <div className="empty-state">
                  <h2>No items match</h2>
                  <p>Try a different search or filter.</p>
                  <button type="button" className="btn" onClick={clearSearch}>
                    Clear search
                  </button>
                </div>
              ) : (
                <div className="takeoff-table-scroll">
                  <table className="data-table takeoff-table">
                    <thead>
                      <tr>
                        {visibleColumns.map((column) => (
                          <th key={column.key} scope="col">
                            <button type="button" className="takeoff-sort" onClick={() => toggleSort(column.key)}>
                              Sort by {column.label}
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((item) => {
                        const isSelected = item.id === selectedItemId;
                        const selectThisRow = () => selectItem(item.id);
                        return (
                          <tr
                            key={item.id}
                            ref={isSelected ? selectedRowRef : null}
                            tabIndex={0}
                            aria-selected={isSelected}
                            className={isSelected ? "is-selected" : undefined}
                            onClick={selectThisRow}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                if (event.key === " ") event.preventDefault();
                                selectThisRow();
                              }
                            }}
                          >
                            {visibleColumns.map((column) => {
                              if (column.key === "status") {
                                return (
                                  <td key={column.key}>
                                    <Pill status={displayStatus(item)} />
                                  </td>
                                );
                              }
                              // The item-name cell names which item the row
                              // describes, so it is the row's header rather
                              // than an ordinary data cell -- a screen-reader
                              // user stepping cell-to-cell needs that
                              // association read out with every other value
                              // in the row (WCAG 2.2 AA).
                              if (column.key === "name") {
                                return (
                                  <th key={column.key} scope="row">
                                    {column.render(item, renderCtx)}
                                  </th>
                                );
                              }
                              return (
                                <td key={column.key} className={column.align === "right" ? "tabular" : undefined}>
                                  {column.render(item, renderCtx)}
                                </td>
                              );
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )
        ) : null}
      </div>
    </>
  );
}
