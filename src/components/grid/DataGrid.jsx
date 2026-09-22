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

   Shift+arrow and Shift+click grow a range from an anchor; the focus
   is still the one active cell. Every cell in the range is
   aria-selected; only the focus carries data-active and the ring, so
   a range reads as a wash and never as a status.
   ============================================================ */

import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import { isEditable, useGridNavigation } from "./useGridNavigation.js";
import { clearChanges, extend, fillChanges, normalize, parseClipboard, pasteChanges, selectAll, sortRows, toTsv } from "./useGridSelection.js";

const cellId = (row, col) => `${row}:${col}`;

function parseNumber(raw, edit) {
  const n = Number(raw);
  if (raw.trim() === "" || !Number.isFinite(n)) return { error: "Enter a number" };
  if (edit.min != null && n < edit.min) return { error: edit.minMessage || `Enter a number of at least ${edit.min}` };
  return { value: n };
}

const DataGrid = forwardRef(function DataGrid(
  { columns, rows: sourceRows, rowKey, rowLabel, onCommit, onCommitRange, onCancel, onUndo, onRedo, footer, caption },
  ref,
) {
  // Sorting reorders once, Sheets-style: `order` (row keys) is set when
  // a header is clicked and again only when the set of keys changes (a
  // reload). A cell edit that changes the sorted value does not move
  // its row until the header is clicked again -- rows jumping under an
  // estimator mid-Tab is the failure this avoids.
  const [sort, setSort] = useState(null); // { key, direction } | null
  const [order, setOrder] = useState(null); // row keys | null = load order
  const keysSignature = sourceRows.map(rowKey).join("\n");
  const rows = useMemo(() => {
    if (!order) return sourceRows;
    const byKey = new Map(sourceRows.map((r) => [rowKey(r), r]));
    const out = [];
    for (const k of order) {
      if (byKey.has(k)) {
        out.push(byKey.get(k));
        byKey.delete(k);
      }
    }
    return [...out, ...byKey.values()];
  }, [sourceRows, order, rowKey]);

  const applySort = (next) => {
    setSort(next);
    if (!next) {
      setOrder(null);
      return;
    }
    const column = columns.find((c) => c.key === next.key);
    setOrder(sortRows(sourceRows, column, next.direction).map(rowKey));
  };

  const firstSignature = useRef(keysSignature);
  useEffect(() => {
    if (firstSignature.current === keysSignature) return;
    firstSignature.current = keysSignature;
    if (sort) applySort(sort);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keysSignature]);

  function onSortClick(column) {
    const cur = sort && sort.key === column.key ? sort.direction : null;
    const next = cur === null ? "ascending" : cur === "ascending" ? "descending" : null;
    setAnchor(null);
    applySort(next ? { key: column.key, direction: next } : null);
  }

  const { active, setActive, move } = useGridNavigation(columns, rows);
  // The other end of the selection. null means "same as the active
  // cell" -- a single-cell selection, the state every earlier
  // behaviour was written for. Shift+arrow and Shift+click set it;
  // every plain move, click, commit, or Escape clears it.
  const [anchor, setAnchor] = useState(null);
  const selection = useMemo(() => (active ? { anchor: anchor || active, focus: active } : null), [anchor, active]);
  const range = useMemo(() => (selection ? normalize(selection, columns) : null), [selection, columns]);
  const isRange = Boolean(range && (range.r0 !== range.r1 || range.c0 !== range.c1));
  // { row, col, value, message, caret } while an editor is open.
  const [editing, setEditing] = useState(null);
  const cells = useRef(new Map());
  const editorRef = useRef(null);
  // The table element, so a copy can tell a real text selection an
  // estimator drag-selected inside a cell (a seller name, a basis note)
  // apart from the grid's own cell/range selection, which carries no
  // window selection at all.
  const tableRef = useRef(null);
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
  // The fill handle drag. `fillDrag` is the source range while the
  // mouse is down (null otherwise); `fillTo` is the last row the pointer
  // entered -- state so the target cells re-render with their dashed
  // outline, mirrored in a ref so the mouseup handler reads the latest
  // value without a stale closure.
  const fillDrag = useRef(null);
  const fillToRef = useRef(null);
  const [fillTo, setFillTo] = useState(null);
  // The in-flight mouseup listener, so an unmount mid-drag can remove
  // it -- otherwise it stays on `document` with a stale closure and
  // still fires a dispatch against a grid that no longer exists.
  const fillUp = useRef(null);

  useEffect(() => {
    return () => {
      if (fillUp.current) document.removeEventListener("mouseup", fillUp.current);
    };
  }, []);

  // Column widths, set on the first resize drag: key -> px. Rendering
  // stays auto-layout until then, so an estimator who never resizes
  // sees exactly today's table.
  const DEFAULT_WIDTH = 120;
  const MIN_WIDTH = 60;
  const [widths, setWidths] = useState(null);
  const [resizing, setResizing] = useState(false);
  const headers = useRef(new Map());
  // The in-flight resize listeners, so an unmount mid-drag can remove
  // them -- otherwise they stay on `document` with a stale closure and
  // still fire a dispatch against a grid that no longer exists.
  const resizeListeners = useRef(null);

  useEffect(() => {
    return () => {
      if (resizeListeners.current) {
        document.removeEventListener("mousemove", resizeListeners.current.onMove);
        document.removeEventListener("mouseup", resizeListeners.current.onUp);
      }
    };
  }, []);

  function startResize(event, key) {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    // First drag: snapshot what the browser's auto layout gave every
    // column, so only the dragged one moves from here on.
    const base = widths || new Map(columns.map((c) => [c.key, headers.current.get(c.key)?.offsetWidth || DEFAULT_WIDTH]));
    const startWidth = base.get(key);
    setWidths(base);
    setResizing(true);
    const onMove = (e) => {
      const next = new Map(base);
      next.set(key, Math.max(MIN_WIDTH, startWidth + e.clientX - startX));
      setWidths(next);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      resizeListeners.current = null;
      setResizing(false);
    };
    resizeListeners.current = { onMove, onUp };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  useEffect(() => {
    if (focusPending.current && active && !editing) {
      focusPending.current = false;
      const el = cells.current.get(cellId(active.row, active.col));
      if (el) el.focus();
    }
  }, [active, editing]);

  useEffect(() => {
    if (anchor && anchor.row >= rows.length) setAnchor(null);
  }, [anchor, rows.length]);

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
    setAnchor(null);
    setActive(next);
  }

  // Moves the focus and keeps the anchor -- Shift+arrow, Shift+click.
  function extendTo(next) {
    if (!next || !active) return;
    focusPending.current = true;
    if (!anchor) setAnchor(active);
    setActive(next);
  }

  function collapse() {
    setAnchor(null);
  }

  /** Every range operation ends here: the screen gets the whole list
   *  once (onCommitRange) or, on a grid without it, one onCommit per
   *  change in order. An empty list is nothing -- no call, no toast. */
  function dispatchRange(changes, kind) {
    if (!changes.length) return;
    if (onCommitRange) onCommitRange(changes, { kind });
    else for (const c of changes) onCommit(c.row, c.key, c.value);
  }

  function copyText() {
    return range ? toTsv(range, columns, rows) : "";
  }

  function startFill(event) {
    event.preventDefault();
    event.stopPropagation();
    if (!range) return;
    fillDrag.current = range;
    fillToRef.current = range.r1;
    setFillTo(range.r1);
    const onUp = () => {
      document.removeEventListener("mouseup", onUp);
      fillUp.current = null;
      const source = fillDrag.current;
      const to = fillToRef.current;
      fillDrag.current = null;
      fillToRef.current = null;
      setFillTo(null);
      if (source && to != null && to > source.r1) {
        dispatchRange(fillChanges(source, columns, rows, { to }), "fill");
        focusPending.current = true;
        setAnchor({ row: source.r0, col: columns[source.c0].key });
        setActive({ row: to, col: columns[source.c1].key });
      }
    };
    fillUp.current = onUp;
    document.addEventListener("mouseup", onUp);
  }

  function onCellMouseEnter(row) {
    if (!fillDrag.current) return;
    fillToRef.current = row;
    setFillTo(row);
  }

  // True when the browser has a real, non-collapsed text selection
  // inside this table -- an estimator drag-selecting a seller name or a
  // basis note, say -- which a copy must leave to the browser's own
  // default handling rather than overwriting with the range's TSV.
  function hasTextSelectionInTable() {
    const sel = window.getSelection();
    return Boolean(sel && !sel.isCollapsed && tableRef.current && tableRef.current.contains(sel.anchorNode));
  }

  function onCopy(event) {
    if (editing || !range) return; // the input's own copy
    if (hasTextSelectionInTable()) return;
    event.clipboardData.setData("text/plain", copyText());
    event.preventDefault();
  }

  function onPaste(event) {
    if (editing || !range) return;
    event.preventDefault();
    const text = event.clipboardData.getData("text/plain");
    dispatchRange(pasteChanges(parseClipboard(text), range, columns, rows), "paste");
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
    // And the close that just set `closing` is over: the open-effect
    // below resets it too, but only when the cell identity changes, so
    // a same-cell reopen from inside onCommit (openEditor on the cell
    // that just committed) would otherwise leave the reopened editor
    // ignoring its own blur.
    closing.current = false;
    reopenedDuringCommit.current = true;
    setActive({ row, col });
    setAnchor(null);
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
    // A read-only cell can hold its own interactive content -- the
    // Material pricing grid's market-evidence <details>/<summary> and
    // seller <a>, so far. Its own focusable descendants own their own
    // keyboard handling, Tab included: without this guard, this
    // handler's Tab logic below fires on the bubbled event before the
    // browser's default and redirects focus onto the grid's (possibly
    // stale) active cell instead of leaving that element's own tab
    // order alone.
    if (event.target !== event.currentTarget && event.target.closest("a, button, summary, input, select, textarea, [contenteditable]")) {
      return;
    }
    const SHIFT_MOVES = { ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down" };
    if (event.shiftKey && SHIFT_MOVES[event.key] && selection) {
      event.preventDefault();
      extendTo(extend(selection, SHIFT_MOVES[event.key], columns, rows).focus);
      return;
    }
    if (MOVES[event.key]) {
      event.preventDefault();
      activate(move(MOVES[event.key]));
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      event.preventDefault();
      const all = selectAll(columns, rows);
      if (all) {
        focusPending.current = true;
        setAnchor(all.anchor);
        setActive(all.focus);
      }
      return;
    }
    if (event.key === "Escape") {
      collapse();
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
    const mod = event.ctrlKey || event.metaKey;
    if (mod && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) onRedo?.();
      else onUndo?.();
      return;
    }
    if (mod && event.key.toLowerCase() === "c") {
      // Browsers differ on whether Ctrl/Cmd+C fires `copy` on a focused
      // non-editable element with no text selection; the copy handler
      // above covers the ones that do, this covers the rest. Both may
      // run and write the same text. Same guard as onCopy: a real text
      // selection inside the table wins.
      if (hasTextSelectionInTable()) return;
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) navigator.clipboard.writeText(copyText()).catch(() => {});
      return;
    }
    if (mod && event.key.toLowerCase() === "d") {
      event.preventDefault();
      if (range && range.r1 > range.r0) dispatchRange(fillChanges(range, columns, rows), "fill");
      return;
    }
    if ((event.key === "Delete" || event.key === "Backspace") && isRange) {
      event.preventDefault();
      dispatchRange(clearChanges(range, columns, rows), "clear");
      return;
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

  function onCellClick(event, row, column) {
    // A click on interactive content inside a cell -- the seller
    // <details>, a link -- belongs to that content: it neither moves
    // focus onto the cell nor selects it.
    if (event.target !== event.currentTarget && event.target.closest("a, button, summary, input, select, textarea, [contenteditable]")) {
      return;
    }
    const next = { row, col: column.key };
    if (event.shiftKey) {
      extendTo(next);
      return;
    }
    const isActive = active && active.row === row && active.col === column.key;
    if (isActive && !editing && !anchor && isEditable(column, rows[row])) startEdit(row, column.key, { caret: "end" });
    else if (!isActive || anchor) activate(next);
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
    const ci = columns.indexOf(column);
    const inRange = Boolean(range && row >= range.r0 && row <= range.r1 && ci >= range.c0 && ci <= range.c1);
    const showClear = isActive && !isRange && !isEditing && editable && column.edit.hasEntry && column.edit.hasEntry(r);
    const showHandle = Boolean(range && row === range.r1 && ci === range.c1 && !isEditing);
    const drag = fillDrag.current;
    const fillTarget = Boolean(drag && fillTo != null && row > drag.r1 && row <= fillTo && ci >= drag.c0 && ci <= drag.c1);
    return (
      <Tag
        key={column.key}
        scope={column.header ? "row" : undefined}
        role={column.header ? "rowheader" : "gridcell"}
        ref={(el) => (el ? cells.current.set(id, el) : cells.current.delete(id))}
        tabIndex={isActive ? 0 : -1}
        aria-selected={inRange || undefined}
        data-active={isActive || undefined}
        data-editable={editable || undefined}
        data-clearable={showClear || undefined}
        data-fill-target={fillTarget || undefined}
        className={className}
        style={{ textAlign: column.align }}
        onClick={(event) => onCellClick(event, row, column)}
        onKeyDown={(event) => onCellKeyDown(event, row, column)}
        onMouseEnter={() => onCellMouseEnter(row)}
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
                tabIndex={-1}
                onClick={(event) => {
                  event.stopPropagation();
                  clear(row, column);
                }}
              >
                <X size={14} aria-hidden="true" />
              </button>
            ) : null}
            {showHandle ? (
              <div
                className="grid-fill-handle"
                aria-hidden="true"
                onMouseDown={startFill}
                onClick={(event) => event.stopPropagation()}
              />
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
      <table
        ref={tableRef}
        className={"data-table takeoff-table grid" + (resizing ? " is-resizing" : "")}
        role="grid"
        aria-multiselectable="true"
        style={widths ? { tableLayout: "fixed", width: [...widths.values()].reduce((a, b) => a + b, 0) + "px" } : undefined}
        onCopy={onCopy}
        onPaste={onPaste}
      >
        <caption className="sr-only">{caption}</caption>
        {widths ? (
          <colgroup>
            {columns.map((c) => (
              <col key={c.key} style={{ width: widths.get(c.key) + "px" }} />
            ))}
          </colgroup>
        ) : null}
        <thead>
          <tr role="row">
            {columns.map((c) => {
              const dir = sort && sort.key === c.key ? sort.direction : null;
              return (
                <th
                  key={c.key}
                  ref={(el) => (el ? headers.current.set(c.key, el) : headers.current.delete(c.key))}
                  scope="col"
                  role="columnheader"
                  aria-sort={dir || undefined}
                  style={{ textAlign: c.align }}
                >
                  <button type="button" className="grid-sort" onClick={() => onSortClick(c)}>
                    {c.label}
                    {dir === "ascending" ? <ArrowUp size={12} aria-hidden="true" /> : null}
                    {dir === "descending" ? <ArrowDown size={12} aria-hidden="true" /> : null}
                  </button>
                  <div
                    className="grid-resize"
                    role="presentation"
                    onMouseDown={(event) => startResize(event, c.key)}
                    onClick={(event) => event.stopPropagation()}
                  />
                </th>
              );
            })}
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
