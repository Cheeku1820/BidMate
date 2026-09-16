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
  render(
    <DataGrid
      ref={ref} columns={columns} rows={rows} rowKey={(r) => r.id} rowLabel={(r) => r.name}
      onCommit={onCommit} onCancel={onCancel} caption="Test grid" {...extra}
    />,
  );
  return { onCommit, onCancel, ref };
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
  });

  test("marks editable cells and not read-only or disabled ones", () => {
    setup();
    expect(cell(0, HOURS)).toHaveAttribute("data-editable");
    expect(cell(0, 0)).not.toHaveAttribute("data-editable");
    expect(cell(1, BASIS)).not.toHaveAttribute("data-editable");
  });
});

describe("moving the active cell", () => {
  test("arrow keys move over editable cells only and focus follows", () => {
    setup();
    fireEvent.keyDown(cell(0, HOURS), { key: "ArrowRight" });
    expect(cell(0, NOTE)).toHaveAttribute("aria-selected", "true");
    expect(document.activeElement).toBe(cell(0, NOTE));
    fireEvent.keyDown(cell(0, NOTE), { key: "ArrowDown" });
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(cell(1, NOTE), { key: "ArrowRight" }); // row 2's basis is disabled
    expect(cell(1, NOTE)).toHaveAttribute("aria-selected", "true");
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
    fireEvent.click(clear);
    expect(onCommit).toHaveBeenCalledWith(rows[0], "hours", null);
    fireEvent.click(cell(1, HOURS));
    expect(within(cell(1, HOURS)).queryByRole("button", { name: "Clear entry" })).not.toBeInTheDocument();
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
