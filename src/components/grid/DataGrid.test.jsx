/* ============================================================
   DataGrid.test.jsx — the grid's behaviour on plain data
   (docs/specs/pricing-grid.md, "Testing → DataGrid.test.jsx").

   Gridcells are located by position: the row header is a rowheader,
   not a gridcell, so each row exposes four gridcells in column order
   qty, hours, note, basis.
   ============================================================ */

import { createRef } from "react";
import { describe, expect, test, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import DataGrid from "./DataGrid.jsx";

const columns = [
  { key: "name", label: "Item", align: "left", header: true, render: (r) => r.name },
  { key: "qty", label: "Quantity", align: "right", render: (r) => r.qty },
  {
    key: "hours", label: "Hours", align: "right",
    render: (r) => (r.hours == null ? "—" : String(r.hours)),
    edit: { kind: "number", min: 0, minMessage: "Hours can't be negative", value: (r) => r.hours, hasEntry: (r) => r.entered },
  },
  {
    key: "note", label: "Note", align: "left",
    render: (r) => r.note || "—",
    edit: { kind: "text", value: (r) => r.note, required: (r) => r.mustNote, requiredMessage: "A note is needed" },
  },
  {
    key: "basis", label: "Basis", align: "left",
    render: (r) => r.basis,
    edit: {
      kind: "select", value: (r) => r.basis, disabled: (r) => r.locked,
      options: [{ value: "a", label: "A" }, { value: "b", label: "B" }],
    },
  },
];
const rows = [
  { id: "r1", name: "One", qty: 1, hours: 0.5, entered: true, note: "", basis: "a" },
  { id: "r2", name: "Two", qty: 2, hours: null, entered: false, note: "x", basis: "b", locked: true },
  { id: "r3", name: "Three", qty: 3, hours: 1, entered: true, note: "", mustNote: true, basis: "a" },
];

function setup(extra = {}) {
  const onCommit = vi.fn();
  const onCancel = vi.fn();
  const ref = createRef();
  const { unmount } = render(
    <DataGrid
      ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
      onCommit={onCommit} onCancel={onCancel} caption="Test grid" {...extra}
    />,
  );
  return { onCommit, onCancel, ref, unmount };
}

/** gridcell at (row index, column among qty/hours/note/basis). */
function cell(row, col) {
  const bodyRows = screen.getAllByRole("row").slice(1); // skip the header row
  return within(bodyRows[row]).getAllByRole("gridcell")[col];
}
const HOURS = 1, NOTE = 2, BASIS = 3;

describe("DataGrid markup", () => {
  test("is a grid with a caption, one tabbable cell, and it is the first editable one", () => {
    setup();
    expect(screen.getByRole("grid", { name: "Test grid" })).toBeInTheDocument();
    const tabbable = document.querySelectorAll('[role="gridcell"][tabindex="0"]');
    expect(tabbable).toHaveLength(1);
    expect(tabbable[0]).toBe(cell(0, HOURS));
    expect(cell(0, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(cell(0, HOURS)).toHaveAttribute("data-active");
    expect(screen.getByRole("grid")).toHaveAttribute("aria-multiselectable", "true");
  });

  test("marks editable cells and not read-only or disabled ones", () => {
    setup();
    expect(cell(0, HOURS)).toHaveAttribute("data-editable");
    expect(cell(0, 0)).not.toHaveAttribute("data-editable");
    expect(cell(1, BASIS)).not.toHaveAttribute("data-editable");
  });

  test("wraps the table in its own scroll container, so the sticky header and footer have something to pin to", () => {
    // jsdom has no layout: this only guards the wrapper class. The chain
    // that makes sticky work is .app-shell-main (column flex, overflow-y
    // auto) -> .page--fill (flex child, min-height 0) -> .grid-scroll
    // (flex child, min-height 0, overflow auto) -> the table.
    setup();
    expect(screen.getByRole("grid").parentElement).toHaveClass("grid-scroll");
    expect(screen.getByRole("grid").parentElement).not.toHaveClass("takeoff-table-scroll");
  });
});

describe("moving the active cell", () => {
  test("arrow keys move one cell in any direction, read-only cells included, and focus follows", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight" });
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(0, NOTE));
    fireEvent.keyDown(cell(0, NOTE), { key: "ArrowDown" });
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowRight" }); // row 2's basis is disabled, still reachable
    expect(cell(1, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, BASIS), { key: "ArrowLeft" });
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowLeft" });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowLeft" });
    expect(cell(1, 0)).toHaveAttribute("aria-selected", "true"); // the read-only Quantity cell
    expect(document.activeElement).toBe(cell(1, 0));
  });

  test("Home and End reach the row's first and last cell; Tab from a read-only cell goes to the next editable one", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, BASIS), { key: "Home" });
    const header = screen.getAllByRole("rowheader")[0];
    expect(header).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(header);
    fireEvent.keyDown(header, { key: "Tab" });
    expect(cell(0, HOURS)).toHaveAttribute("aria-selected", "true");
  });

  test("Enter, a printable key, and Delete do nothing on a read-only cell", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // onto Quantity
    expect(cell(0, 0)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, 0), { key: "Enter" });
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.keyDown(cell(0, 0), { key: "5" });
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.keyDown(cell(0, 0), { key: "Delete" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("Tab wraps to the next row and Shift+Tab back", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(0, BASIS), { key: "Tab" });
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, HOURS), { key: "Tab", shiftKey: true });
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
  });

  test("clicking an editable cell makes it active; a second click opens the editor", () => {
    setup();
    fireEvent.click(cell(2, HOURS));
    expect(cell(2, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    fireEvent.click(cell(2, HOURS));
    expect(screen.getByRole("textbox", { name: "Hours, Three" })).toHaveValue("1");
  });
});

describe("editing", () => {
  test("a printable key opens the editor with that character; Enter commits and moves down", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "7" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(input).toHaveValue("7");
    expect(input).toHaveAttribute("inputmode", "decimal");
    fireEvent.change(input, { target: { value: "7.5" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", 7.5);
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(1, HOURS));
  });

  test("Enter opens with the current value; Escape discards, stays, and reports the cancel", () => {
    const { onCommit, onCancel } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(input).toHaveValue("0.5");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledWith(rows[0], "hours");
    expect(document.activeElement).toBe(cell(0, HOURS));
  });

  test("F2 opens the editor with the current value and the caret at the end", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "F2" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(input).toHaveValue("0.5");
    expect(input.selectionStart).toBe(input.value.length);
    expect(document.activeElement).toBe(input);
  });

  test("Tab commits and moves right; an unchanged value commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Tab" });
    expect(onCommit).not.toHaveBeenCalled();
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
  });

  test("blur commits", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, NOTE), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Note, One" });
    fireEvent.change(input, { target: { value: "checked" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledWith(rows[0], "note", "checked");
  });

  test("a select cell opens on Space and commits on change", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    fireEvent.keyDown(cell(0, BASIS), { key: " " });
    const select = screen.getByRole("combobox", { name: "Basis, One" });
    fireEvent.change(select, { target: { value: "b" } });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "basis", "b");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(cell(0, BASIS)).toHaveAttribute("aria-selected", "true");
  });
});

describe("validation", () => {
  test("a non-number keeps the editor open with a message and commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "a" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", screen.getByRole("alert").id);
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("below the minimum shows the column's message", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "-" });
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "-1" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Hours can't be negative");
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("emptying a required text cell is refused with its message", () => {
    const { onCommit } = setup();
    fireEvent.click(cell(2, NOTE));
    fireEvent.keyDown(cell(2, NOTE), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("A note is needed");
    expect(onCommit).not.toHaveBeenCalled();
  });
});

describe("clearing an entry", () => {
  test("emptying the editor on a cell with an entry commits null; without an entry commits nothing", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    onCommit.mockClear();
    fireEvent.click(cell(1, HOURS));
    fireEvent.keyDown(cell(1, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("Delete on an active cell clears an entry and does nothing without one", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Delete" });
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    onCommit.mockClear();
    fireEvent.click(cell(1, HOURS));
    fireEvent.keyDown(cell(1, HOURS), { key: "Backspace" });
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("the Clear button renders only on an active cell with an entry, and clears on click", () => {
    const { onCommit } = setup();
    const clear = within(cell(0, HOURS)).getByRole("button", { name: "Clear entry" });
    expect(clear).toHaveAttribute("tabindex", "-1"); // Delete/Backspace are the keyboard path
    expect(cell(0, HOURS)).toHaveAttribute("data-clearable"); // the padding for it lands only here
    fireEvent.click(clear);
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    fireEvent.click(cell(1, HOURS));
    expect(within(cell(1, HOURS)).queryByRole("button", { name: "Clear entry" })).not.toBeInTheDocument();
    expect(cell(1, HOURS)).not.toHaveAttribute("data-clearable");
    expect(within(cell(0, HOURS)).queryByRole("button", { name: "Clear entry" })).not.toBeInTheDocument();
  });
});

describe("openEditor", () => {
  test("opens a named cell's editor with a message already showing", () => {
    const { ref } = setup();
    act(() => ref.current.openEditor("r2", "note", { message: "Say why" }));
    expect(screen.getByRole("textbox", { name: "Note, Two" })).toHaveValue("x");
    expect(screen.getByRole("alert")).toHaveTextContent("Say why");
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
  });
});

describe("footer", () => {
  test("renders the footer row inside tfoot", () => {
    setup({ footer: <tr><td colSpan={5}>Total 1.5</td></tr> });
    expect(screen.getByText("Total 1.5").closest("tfoot")).not.toBeNull();
  });
});

describe("range selection", () => {
  const selected = () => document.querySelectorAll('[aria-selected="true"]');

  test("Shift+ArrowRight extends over a read-only cell; the focus alone is data-active", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // Quantity
    fireEvent.keyDown(cell(0, 0), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(selected()).toHaveLength(4);
    expect(cell(0, 0)).toHaveAttribute("aria-selected", "true");
    expect(cell(1, HOURS)).toHaveAttribute("aria-selected", "true");
    expect(document.querySelectorAll("[data-active]")).toHaveLength(1);
    expect(cell(1, HOURS)).toHaveAttribute("data-active");
    expect(document.activeElement).toBe(cell(1, HOURS));
  });

  test("a plain arrow collapses the range, and so does Escape", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(selected()).toHaveLength(2);
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowUp" });
    expect(selected()).toHaveLength(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "Escape" });
    expect(selected()).toHaveLength(1);
    expect(cell(1, HOURS)).toHaveAttribute("data-active");
  });

  test("Shift+click extends from the anchor; Ctrl+A covers the grid", () => {
    setup();
    fireEvent.click(cell(2, NOTE), { shiftKey: true });
    expect(selected()).toHaveLength(6); // rows 0–2 × hours, note
    expect(cell(2, NOTE)).toHaveAttribute("data-active");
    fireEvent.keyDown(cell(2, NOTE), { key: "a", ctrlKey: true });
    expect(selected()).toHaveLength(15); // 3 rows × 5 columns, rowheaders included
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  test("clicking a read-only cell makes it active with no editor; clicking a link inside a cell does not", () => {
    const withLink = [...columns];
    withLink[1] = { ...columns[1], render: (r) => <a href="https://example.test">{r.qty}</a> };
    const { onCommit } = setup({ columns: withLink });
    fireEvent.click(cell(1, 0));
    expect(cell(1, 0)).toHaveAttribute("data-active");
    expect(document.activeElement).toBe(cell(1, 0));
    fireEvent.click(cell(1, 0));
    expect(screen.queryByRole("textbox")).toBeNull();
    const link = screen.getAllByRole("link")[2];
    link.focus();
    fireEvent.click(link);
    expect(cell(2, 0)).not.toHaveAttribute("data-active");
    expect(document.activeElement).toBe(link);
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("the Clear button never renders over a multi-cell range", () => {
    setup();
    expect(screen.getByRole("button", { name: "Clear entry" })).toBeInTheDocument();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    expect(screen.queryByRole("button", { name: "Clear entry" })).toBeNull();
  });
});

/* ============================================================
   Fix round (task-6 review): four Important defects found in the
   brief's own DataGrid.jsx. One focused test per defect, below.
   ============================================================ */

describe("fix round: caret position while typing", () => {
  test("does not force the caret to the end on every keystroke", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    // The open itself is allowed one caret placement; spy after that,
    // so this only catches the effect re-firing on later keystrokes.
    const spy = vi.spyOn(input, "setSelectionRange");
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.change(input, { target: { value: "9.5" } });
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("fix round: commit ordering", () => {
  test("a commit that reopens another cell's editor (from onCommit) is not clobbered by the trailing close", () => {
    const ref = createRef();
    const onCommit = vi.fn(() => ref.current.openEditor("r1", "note"));
    render(
      <DataGrid
        ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
        onCommit={onCommit} caption="Test grid"
      />,
    );
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox", { name: "Hours, One" }), { target: { value: "9" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Hours, One" }), { key: "Enter" });
    // The reentrant openEditor call wins: the Note editor is open, not
    // clobbered by the Hours editor's own trailing closeEditor().
    expect(screen.getByRole("textbox", { name: "Note, One" })).toHaveValue("");
  });
});

describe("fix round: closing does not leak into a same-cell reopen", () => {
  test("an editor reopened on the same cell from onCommit still commits on blur", async () => {
    const ref = createRef();
    const onCommit = vi.fn(() => ref.current.openEditor("r1", "hours", { message: "Try again" }));
    render(
      <DataGrid
        ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
        onCommit={onCommit} caption="Test grid"
      />,
    );
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox", { name: "Hours, One" }), { target: { value: "9" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Hours, One" }), { key: "Enter" });
    expect(onCommit).toHaveBeenCalledTimes(1);
    // Reopened on the same cell, with the message.
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    expect(screen.getByRole("alert")).toHaveTextContent("Try again");
    // Same cell, so the open-effect keyed on cell identity did not
    // re-run to reset `closing`; startEdit has to. Otherwise this
    // reopened editor ignores its own blur and the second value is lost.
    fireEvent.change(input, { target: { value: "11" } });
    fireEvent.blur(input);
    expect(onCommit).toHaveBeenCalledTimes(2);
    expect(onCommit).toHaveBeenLastCalledWith(rows[0], "hours", 11);
  });
});

describe("fix round: focusPending does not leak", () => {
  // Both cases below check document.activeElement after a blur.
  // `button.focus()` runs outside act, and jsdom fires `focusout` on
  // the editor right then -- so React's onBlur has already run and
  // scheduled the close outside act by the time the explicit
  // `fireEvent.blur` fires, which is a second blur on a stale closure.
  // The refocus effect from that first, un-acted close has not
  // flushed, so without `await act(async () => {})` the assertion
  // reads document.activeElement before the effect could have moved
  // it, and passes regardless of whether the bug is fixed.

  test("an editor opened reentrantly from onCommit does not later yank focus back into the grid on its own blur", async () => {
    const ref = createRef();
    const onCommit = vi.fn(() => ref.current.openEditor("r1", "note"));
    render(
      <DataGrid
        ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
        onCommit={onCommit} caption="Test grid"
      />,
    );
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox", { name: "Hours, One" }), { target: { value: "9" } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Hours, One" }), { key: "Enter" });
    const input = screen.getByRole("textbox", { name: "Note, One" });

    // Its own later close (focus moving to something outside the grid)
    // must not yank focus back to a grid cell -- that would mean the
    // stale focusPending flag from the Hours editor's own close leaked
    // through, since openEditor was called before that close resolved.
    const button = document.createElement("button");
    document.body.appendChild(button);
    button.focus();
    fireEvent.blur(input);
    await act(async () => {});
    expect(document.activeElement).toBe(button);
    document.body.removeChild(button);
  });

  test("a select editor's blur does not steal focus back into the grid", async () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "End" });
    fireEvent.keyDown(cell(0, BASIS), { key: " " });
    const select = screen.getByRole("combobox", { name: "Basis, One" });
    const button = document.createElement("button");
    document.body.appendChild(button);
    button.focus();
    fireEvent.blur(select);
    await act(async () => {});
    expect(document.activeElement).toBe(button);
    document.body.removeChild(button);
  });
});

describe("fix round: invalid value on blur", () => {
  test("cancels rather than stranding the editor and deadening the keyboard", () => {
    const { onCancel } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "a" });
    const input = screen.getByRole("textbox", { name: "Hours, One" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");
    fireEvent.blur(input);
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(onCancel).toHaveBeenCalledWith(rows[0], "hours");
    fireEvent.click(cell(1, NOTE));
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowUp" });
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
  });
});

describe("fix round: minor items", () => {
  test("Infinity is rejected as not a number", () => {
    const { onCommit } = setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Infinity" } });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a number");
    expect(onCommit).not.toHaveBeenCalled();
  });
});

function clipboardEvent(type, data = {}) {
  // jsdom has no ClipboardEvent constructor with clipboardData; a plain
  // Event with the property attached is what fireEvent passes through.
  const store = { ...data };
  return {
    clipboardData: {
      getData: (t) => store[t] ?? "",
      setData: (t, v) => { store[t] = v; },
      types: Object.keys(store),
    },
    _store: store,
  };
}

describe("clipboard, fill, clear, undo", () => {
  test("copy writes the range as TSV and prevents the default", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowLeft" }); // Quantity
    fireEvent.keyDown(cell(0, 0), { key: "ArrowRight", shiftKey: true });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    const ev = clipboardEvent("copy");
    const prevented = !fireEvent.copy(screen.getByRole("grid"), ev);
    expect(prevented).toBe(true);
    expect(ev._store["text/plain"]).toBe("1\t0.5\n2\t");
  });

  test("copy inside an open editor is left to the input", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    const ev = clipboardEvent("copy");
    const prevented = !fireEvent.copy(screen.getByRole("textbox"), ev);
    expect(prevented).toBe(false);
  });

  test("paste maps the clip through onCommitRange and never through onCommit", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "2\tfirst\r\n3\tsecond\r\n" }));
    expect(onCommit).not.toHaveBeenCalled();
    expect(onCommitRange).toHaveBeenCalledTimes(1);
    expect(onCommitRange).toHaveBeenCalledWith(
      [
        { row: rows[0], key: "hours", value: 2 },
        { row: rows[0], key: "note", value: "first" },
        { row: rows[1], key: "hours", value: 3 },
        { row: rows[1], key: "note", value: "second" },
      ],
      { kind: "paste" },
    );
  });

  test("a paste with nothing applicable calls nothing; a paste while editing is left to the input", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "abc" }));
    expect(onCommitRange).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.paste(screen.getByRole("textbox"), clipboardEvent("paste", { "text/plain": "7" }));
    expect(onCommitRange).not.toHaveBeenCalled();
    expect(onCommit).not.toHaveBeenCalled();
  });

  test("without onCommitRange a paste goes through onCommit once per change, in order", () => {
    const { onCommit } = setup();
    fireEvent.paste(cell(0, HOURS), clipboardEvent("paste", { "text/plain": "2\n3" }));
    expect(onCommit.mock.calls).toEqual([[rows[0], "hours", 2], [rows[1], "hours", 3]]);
  });

  test("Ctrl+D fills the top row down the range; on one cell it does nothing", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "d", ctrlKey: true });
    expect(onCommitRange).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(2, HOURS), { key: "d", metaKey: true });
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[1], key: "hours", value: 0.5 }, { row: rows[2], key: "hours", value: 0.5 }],
      { kind: "fill" },
    );
  });

  test("Delete over a range clears every entry through onCommitRange; on one cell it still uses onCommit", () => {
    const onCommitRange = vi.fn();
    const { onCommit } = setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(1, HOURS), { key: "ArrowDown", shiftKey: true });
    fireEvent.keyDown(cell(2, HOURS), { key: "Delete" });
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[0], key: "hours", value: null }, { row: rows[2], key: "hours", value: null }],
      { kind: "clear" },
    );
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.keyDown(cell(2, HOURS), { key: "Escape" });
    fireEvent.keyDown(cell(2, HOURS), { key: "Backspace" });
    expect(onCommit).toHaveBeenCalledWith(rows[2], "hours", null);
  });

  test("Ctrl+Z and Ctrl+Shift+Z call onUndo and onRedo on a cell, never inside an editor", () => {
    const onUndo = vi.fn(), onRedo = vi.fn();
    setup({ onUndo, onRedo });
    fireEvent.keyDown(cell(0, HOURS), { key: "z", metaKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "Z", ctrlKey: true, shiftKey: true });
    expect(onRedo).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(cell(0, HOURS), { key: "Enter" });
    fireEvent.keyDown(screen.getByRole("textbox"), { key: "z", metaKey: true });
    expect(onUndo).toHaveBeenCalledTimes(1);
  });
});

describe("fill handle", () => {
  const handle = () => document.querySelector(".grid-fill-handle");

  test("renders only in the range's bottom-right cell", () => {
    setup();
    expect(cell(0, HOURS).contains(handle())).toBe(true);
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight", shiftKey: true });
    expect(cell(0, NOTE).contains(handle())).toBe(true);
    expect(document.querySelectorAll(".grid-fill-handle")).toHaveLength(1);
  });

  test("dragging down repeats the source rows onto the rows passed, then extends the selection", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.mouseDown(handle());
    fireEvent.mouseEnter(cell(1, HOURS));
    expect(cell(1, HOURS)).toHaveAttribute("data-fill-target");
    fireEvent.mouseEnter(cell(2, HOURS));
    expect(cell(2, HOURS)).toHaveAttribute("data-fill-target");
    fireEvent.mouseUp(document);
    expect(onCommitRange).toHaveBeenCalledWith(
      [{ row: rows[1], key: "hours", value: 0.5 }, { row: rows[2], key: "hours", value: 0.5 }],
      { kind: "fill" },
    );
    expect(document.querySelectorAll('[aria-selected="true"]')).toHaveLength(3);
    expect(cell(2, HOURS)).toHaveAttribute("data-active");
    expect(cell(2, HOURS)).not.toHaveAttribute("data-fill-target");
  });

  test("releasing on the source row, or above it, fills nothing", () => {
    const onCommitRange = vi.fn();
    setup({ onCommitRange });
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowDown" });
    fireEvent.mouseDown(handle());
    fireEvent.mouseEnter(cell(0, HOURS));
    fireEvent.mouseUp(document);
    expect(onCommitRange).not.toHaveBeenCalled();
  });

  test("unmounting mid-drag removes the document mouseup listener", () => {
    const onCommitRange = vi.fn();
    const { unmount } = setup({ onCommitRange });
    fireEvent.mouseDown(handle());
    fireEvent.mouseEnter(cell(1, HOURS));
    unmount();
    fireEvent.mouseUp(document);
    expect(onCommitRange).not.toHaveBeenCalled();
  });
});
