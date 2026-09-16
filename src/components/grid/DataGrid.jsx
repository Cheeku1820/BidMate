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
  if (raw.trim() === "" || !Number.isFinite(n)) return { error: "Enter a number" };
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
  // Set by startEdit and read right after firing a deferred commit, so
  // Enter/Tab know whether the commit's onCommit reopened a different
  // cell's editor (openEditor, called synchronously from onCommit).
  // When it did, the automatic "move to the next cell" step must be
  // skipped: it would otherwise both stomp the reopened editor's
  // active cell and, via activate(), re-arm focusPending -- which
  // would fire the next time that reopened editor's own close clears
  // `editing`, yanking focus back into the grid out from under
  // whatever the estimator does with it.
  const reopenedDuringCommit = useRef(false);

  useEffect(() => {
    if (focusPending.current && active && !editing) {
      focusPending.current = false;
      const el = cells.current.get(cellId(active.row, active.col));
      if (el) el.focus();
    }
  }, [active, editing]);

  // Runs once per editor *open*, not on every keystroke: keying this on
  // `editing` itself re-fired on every value/message change (a new
  // object each time setEditing is called), which forced the caret to
  // the end while the estimator was still typing or had arrowed into
  // the middle of the value. Keying on the cell identity instead means
  // it only runs when a different cell starts editing.
  useEffect(() => {
    const el = editorRef.current;
    if (!editing || !el) return;
    closing.current = false;
    el.focus();
    if (editing.caret === "end" && typeof el.setSelectionRange === "function") {
      const n = el.value.length;
      el.setSelectionRange(n, n);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing?.row, editing?.col]);

  const columnByKey = (key) => columns.find((c) => c.key === key);

  function activate(next) {
    if (!next) return;
    focusPending.current = true;
    setActive(next);
  }

  function startEdit(row, col, { value, caret, message } = {}) {
    const column = columnByKey(col);
    const current = column.edit.value(rows[row]);
    // An editor is opening, so any earlier request to refocus the grid
    // cell once editing clears no longer applies -- without this, a
    // commit whose onCommit reopens a different cell's editor (the
    // material screen's allowance reason does this) leaves the flag
    // set, and that editor's own later close yanks focus back into the
    // grid out from under whatever the estimator clicked next.
    focusPending.current = false;
    reopenedDuringCommit.current = true;
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

  // Closes without requesting a refocus of the grid cell. A blur means
  // focus has already moved somewhere the estimator chose -- another
  // cell, a control outside the grid -- and pulling it back into the
  // grid a moment later, once this editor's own close finishes, would
  // undo that. `closeEditor` above is for the paths that *do* want the
  // active cell focused afterward: a key-driven move, or Escape landing
  // back on the cell it was already on.
  function closeEditorQuiet() {
    closing.current = true;
    setEditing(null);
  }

  function clear(row, column) {
    const r = rows[row];
    if (column.edit.hasEntry && column.edit.hasEntry(r)) onCommit(r, column.key, null);
  }

  /** Validates the open editor without committing. Returns
   *  `{ ok: true, commit? }` when the value may close the editor --
   *  `commit`, when present, is a thunk that fires `onCommit` once.
   *  It is deferred rather than called here so a caller can close the
   *  editor's own state *before* running it: a screen's `onCommit` may
   *  open a different cell's editor synchronously (`openEditor`), and
   *  if that happened before this editor's close, the close would
   *  overwrite it. Returns `{ ok: false }` and leaves a validation
   *  message in state when the value cannot be committed. */
  function commitEditor() {
    const { row, col, value } = editing;
    const column = columnByKey(col);
    const edit = column.edit;
    const r = rows[row];
    // Defensive: the row this editor was opened for no longer exists
    // (e.g. deleted while the editor was open). Nothing to validate
    // against and nothing to commit.
    if (!r) return { ok: true };
    const current = edit.value(r);
    if (value.trim() === "") {
      if (edit.required && edit.required(r)) {
        setEditing({ ...editing, message: edit.requiredMessage || "This can't be empty" });
        return { ok: false };
      }
      if (edit.hasEntry && edit.hasEntry(r)) return { ok: true, commit: () => onCommit(r, col, null) };
      return { ok: true };
    }
    if (edit.kind === "number") {
      const parsed = parseNumber(value, edit);
      if (parsed.error) {
        setEditing({ ...editing, message: parsed.error });
        return { ok: false };
      }
      if (current == null || Number(current) !== parsed.value) return { ok: true, commit: () => onCommit(r, col, parsed.value) };
      return { ok: true };
    }
    if (value !== String(current ?? "")) return { ok: true, commit: () => onCommit(r, col, value) };
    return { ok: true };
  }

  function onEditorKeyDown(event) {
    if (event.key === "Enter") {
      event.preventDefault();
      const result = commitEditor();
      if (result.ok) {
        // Close, then report, then move -- in that order, so a screen
        // that opens another cell's editor from inside `onCommit` has
        // the last word on `editing`. And if it did reopen one, skip
        // the move: it would stomp that editor's active cell and
        // re-arm a focus request that fires on its later close.
        closeEditor();
        reopenedDuringCommit.current = false;
        result.commit?.();
        if (!reopenedDuringCommit.current) activate(move("down"));
      }
    } else if (event.key === "Tab") {
      event.preventDefault();
      const result = commitEditor();
      if (result.ok) {
        closeEditor();
        reopenedDuringCommit.current = false;
        result.commit?.();
        if (!reopenedDuringCommit.current) activate(move(event.shiftKey ? "prev" : "next") || active);
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
    const result = commitEditor();
    if (result.ok) {
      closeEditorQuiet();
      result.commit?.();
      return;
    }
    // The value is invalid (e.g. still showing "Enter a number") and
    // focus has already left the input -- the estimator clicked
    // something else. Leaving the editor open here strands it: its
    // cell's `editing` no longer matches wherever `active` moves next,
    // and onCellKeyDown drops every key while `editing` is set, so the
    // grid goes dead under the estimator's next click. Treat it as a
    // cancel instead, same as Escape, but without asking for the
    // active cell to be refocused -- the estimator's click already
    // chose where focus goes.
    const { row, col } = editing;
    closeEditorQuiet();
    if (onCancel) onCancel(rows[row], col);
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
            // Quiet, not `closeEditor`: the select is losing focus
            // because the estimator clicked elsewhere, and requesting
            // a refocus of the grid cell here would pull focus back
            // out from under that click once this close finishes.
            if (!closing.current) closeEditorQuiet();
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

  // Its own scroll container, not .takeoff-table-scroll: that box is
  // overflow-x only and has no height bound, so it never scrolls
  // vertically and the sticky thead/tfoot pin to a box that never
  // moves. .grid-scroll is overflow auto with min-height 0, and the
  // pricing pages fill the shell (.page--fill) so it has a height.
  return (
    <div className="grid-scroll">
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
