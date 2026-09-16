/* ============================================================
   DataGrid.jsx — a spreadsheet-like editable table
   (docs/specs/pricing-grid.md, "The grid").

   Cells look like data until you edit them. One cell is active (roving
   tabindex, aria-selected, the focus ring); typing, Enter, or F2 opens
   an editor in place; Enter/Tab commit and move; Escape discards.
   Emptying a cell that carries an estimator entry -- or Delete on it,
   or the × that appears on it -- commits `null`, which the screen
   reads as "clear this and fall back to the next source".

   The grid owns no data. It renders `rows` through `columns` and tells
   the screen `onCommit(row, key, value)` once per changed cell. Status
   and source tiers are ordinary read-only columns whose `render`
   returns the existing Pill / .pill--neutral markup; nothing here
   invents a status treatment, and the active ring is a ring, never a
   fill, so selection cannot read as a status.

   Number editors are text inputs with inputmode="decimal", not
   type="number": the spinner and the browser's own validation get in
   the way of Tab-through entry, and the grid validates itself.
   ============================================================ */

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { X } from "lucide-react";
import { isEditable, useGridNavigation } from "./useGridNavigation.js";

const cellId = (row, col) => `${row}:${col}`;

function parseNumber(raw, edit) {
  const n = Number(raw);
  if (raw.trim() === "" || Number.isNaN(n)) return { error: "Enter a number" };
  if (edit.min != null && n < edit.min) return { error: edit.minMessage || `Enter a number of at least ${edit.min}` };
  return { value: n };
}

const DataGrid = forwardRef(function DataGrid(
  { columns, rows, rowKey, rowLabel, onCommit, onCancel, footer, caption },
  ref,
) {
  const { active, setActive, move } = useGridNavigation(columns, rows);
  // { row, col, value, message, caret } while an editor is open.
  const [editing, setEditing] = useState(null);
  const cells = useRef(new Map());
  const editorRef = useRef(null);
  // Set before any change that should end with the active cell focused
  // -- a key move, a commit, a cancel -- and consumed by the effect
  // below. Not set on mount, so rendering the grid never steals focus.
  const focusPending = useRef(false);
  // Set right before an editor is closed by code, so the blur that
  // closing fires does not commit a second time.
  const closing = useRef(false);

  useEffect(() => {
    if (focusPending.current && active && !editing) {
      focusPending.current = false;
      const el = cells.current.get(cellId(active.row, active.col));
      if (el) el.focus();
    }
  }, [active, editing]);

  useEffect(() => {
    const el = editorRef.current;
    if (!editing || !el) return;
    closing.current = false;
    el.focus();
    if (editing.caret === "end" && typeof el.setSelectionRange === "function") {
      const n = el.value.length;
      el.setSelectionRange(n, n);
    }
  }, [editing]);

  const columnByKey = (key) => columns.find((c) => c.key === key);

  function activate(next) {
    if (!next) return;
    focusPending.current = true;
    setActive(next);
  }

  function startEdit(row, col, { value, caret, message } = {}) {
    const column = columnByKey(col);
    const current = column.edit.value(rows[row]);
    setActive({ row, col });
    setEditing({ row, col, value: value ?? String(current ?? ""), caret, message: message || null });
  }

  useImperativeHandle(
    ref,
    () => ({
      openEditor(rowKeyValue, col, { message } = {}) {
        const row = rows.findIndex((r) => rowKey(r) === rowKeyValue);
        if (row < 0) return;
        startEdit(row, col, { caret: "end", message });
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, columns, rowKey],
  );

  function closeEditor() {
    closing.current = true;
    focusPending.current = true;
    setEditing(null);
  }

  function clear(row, column) {
    const r = rows[row];
    if (column.edit.hasEntry && column.edit.hasEntry(r)) onCommit(r, column.key, null);
  }

  /** Commits the open editor. Returns true when it may close: the value
   *  was valid and (if changed) committed, or unchanged. False leaves
   *  it open with a message. */
  function commitEditor() {
    const { row, col, value } = editing;
    const column = columnByKey(col);
    const edit = column.edit;
    const r = rows[row];
    const current = edit.value(r);
    if (value.trim() === "") {
      if (edit.required && edit.required(r)) {
        setEditing({ ...editing, message: edit.requiredMessage || "This can't be empty" });
        return false;
      }
      if (edit.hasEntry && edit.hasEntry(r)) onCommit(r, col, null);
      return true;
    }
    if (edit.kind === "number") {
      const parsed = parseNumber(value, edit);
      if (parsed.error) {
        setEditing({ ...editing, message: parsed.error });
        return false;
      }
      if (current == null || Number(current) !== parsed.value) onCommit(r, col, parsed.value);
      return true;
    }
    if (value !== String(current ?? "")) onCommit(r, col, value);
    return true;
  }

  function onEditorKeyDown(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      if (commitEditor()) {
        closeEditor();
        activate(move("down"));
      }
    } else if (event.key === "Tab") {
      event.preventDefault();
      if (commitEditor()) {
        closeEditor();
        activate(move(event.shiftKey ? "prev" : "next") || active);
      }
    } else if (event.key === "Escape") {
      event.preventDefault();
      const { row, col } = editing;
      closeEditor();
      if (onCancel) onCancel(rows[row], col);
    }
  }

  function onEditorBlur() {
    if (closing.current || !editing) return;
    if (commitEditor()) {
      closing.current = true;
      setEditing(null);
    }
  }

  function onSelectChange(event) {
    const { row, col } = editing;
    const column = columnByKey(col);
    const next = event.target.value;
    // Close first, report second: a screen may answer the commit by
    // opening another cell's editor (the material screen does, for an
    // allowance's reason), and that has to be the last state write.
    closeEditor();
    if (next !== String(column.edit.value(rows[row]) ?? "")) onCommit(rows[row], col, next);
  }

  const MOVES = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down", Home: "home", End: "end" };

  function onCellKeyDown(event, row, column) {
    if (editing) return;
    if (MOVES[event.key]) {
      event.preventDefault();
      activate(move(MOVES[event.key]));
      return;
    }
    if (event.key === "Tab") {
      const next = move(event.shiftKey ? "prev" : "next");
      if (next) {
        event.preventDefault();
        activate(next);
      }
      return; // null: let Tab leave the grid
    }
    if (!isEditable(column, rows[row])) return;
    const kind = column.edit.kind;
    if (event.key === "Enter" || event.key === "F2") {
      event.preventDefault();
      startEdit(row, column.key, { caret: "end" });
    } else if (event.key === " " && kind === "select") {
      event.preventDefault();
      startEdit(row, column.key);
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      clear(row, column);
    } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey && kind !== "select") {
      event.preventDefault();
      startEdit(row, column.key, { value: event.key, caret: "end" });
    }
  }

  function onCellClick(row, column) {
    if (!isEditable(column, rows[row])) return;
    const isActive = active && active.row === row && active.col === column.key;
    if (isActive && !editing) startEdit(row, column.key, { caret: "end" });
    else if (!isActive) activate({ row, col: column.key });
  }

  function renderEditor(row, column) {
    const label = `${column.label}, ${rowLabel(rows[row])}`;
    const errorId = `grid-error-${cellId(row, column.key)}`;
    const described = editing.message ? errorId : undefined;
    const editor =
      column.edit.kind === "select" ? (
        <select
          ref={editorRef}
          className="grid-editor"
          aria-label={label}
          value={editing.value}
          onChange={onSelectChange}
          onKeyDown={(event) => {
            if (event.key === "Escape" || event.key === "Tab") onEditorKeyDown(event);
          }}
          onBlur={() => {
            if (!closing.current) closeEditor();
          }}
        >
          {column.edit.options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          ref={editorRef}
          className={"grid-editor" + (column.align === "right" ? " tabular" : "")}
          type="text"
          inputMode={column.edit.kind === "number" ? "decimal" : undefined}
          aria-label={label}
          aria-invalid={editing.message ? true : undefined}
          aria-describedby={described}
          value={editing.value}
          onChange={(event) => setEditing({ ...editing, value: event.target.value, message: null })}
          onKeyDown={onEditorKeyDown}
          onBlur={onEditorBlur}
        />
      );
    return (
      <div className="grid-editor-wrap">
        {editor}
        {editing.message ? (
          <div id={errorId} className="grid-cell-error" role="alert">
            {editing.message}
          </div>
        ) : null}
      </div>
    );
  }

  function renderCell(r, row, column) {
    const editable = isEditable(column, r);
    const isActive = Boolean(active && active.row === row && active.col === column.key);
    const isEditing = Boolean(editing && editing.row === row && editing.col === column.key);
    const id = cellId(row, column.key);
    const Tag = column.header ? "th" : "td";
    const extra = column.className ? column.className(r) : undefined;
    const className = [column.align === "right" ? "tabular" : "", extra || ""].join(" ").trim() || undefined;
    const showClear = isActive && !isEditing && editable && column.edit.hasEntry && column.edit.hasEntry(r);
    return (
      <Tag
        key={column.key}
        scope={column.header ? "row" : undefined}
        role={column.header ? "rowheader" : "gridcell"}
        ref={(el) => (el ? cells.current.set(id, el) : cells.current.delete(id))}
        tabIndex={isActive ? 0 : -1}
        aria-selected={isActive || undefined}
        data-editable={editable || undefined}
        className={className}
        style={{ textAlign: column.align }}
        onClick={() => onCellClick(row, column)}
        onKeyDown={(event) => onCellKeyDown(event, row, column)}
      >
        {isEditing ? (
          renderEditor(row, column)
        ) : (
          <>
            {column.render(r)}
            {showClear ? (
              <button
                type="button"
                className="grid-clear"
                aria-label="Clear entry"
                onClick={(event) => {
                  event.stopPropagation();
                  clear(row, column);
                }}
              >
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
          </>
        )}
      </Tag>
    );
  }

  return (
    <div className="takeoff-table-scroll">
      <table className="data-table takeoff-table grid" role="grid">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr role="row">
            {columns.map((c) => (
              <th key={c.key} scope="col" role="columnheader" style={{ textAlign: c.align }}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, row) => (
            <tr key={rowKey(r)} role="row">
              {columns.map((c) => renderCell(r, row, c))}
            </tr>
          ))}
        </tbody>
        {footer ? <tfoot>{footer}</tfoot> : null}
      </table>
    </div>
  );
});

export default DataGrid;
