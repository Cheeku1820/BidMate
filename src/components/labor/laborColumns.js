/* ============================================================
   laborColumns.js — what the Labor workspace shows. Mirrors
   spreadsheetColumns.js's data-driven shape: the header row and the
   body read one list rather than two that can drift.

   Rows come from store.getLaborRows (Task 9's mapLaborRow), one row
   per takeoff item, resolved fresh on every read through the
   precedence chain in docs/superpowers/specs/2026-08-31-labor-material-
   pricing-design.md ("Precedence resolution"). hoursPerUnit/rate/
   adjustedHours/laborCost are all independently nullable -- an item can
   have hours resolved and no rate yet, or neither -- so every numeric
   cell falls back to NONE rather than a fabricated 0.
   ============================================================ */

const NONE = "—";
const money = (n) => "$" + Math.round(Number(n)).toLocaleString();

export const COLUMNS = [
  { key: "itemName", label: "Item", align: "left", render: (row) => row.itemName },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "hoursPerUnit", label: "Hours/unit", align: "right",
    render: (row) => (row.hoursPerUnit != null ? row.hoursPerUnit : NONE),
  },
  { key: "hoursSourceLabel", label: "Hours source", align: "left", render: (row) => row.hoursSourceLabel || NONE },
  {
    key: "rate", label: "Rate", align: "right",
    render: (row) => (row.rate != null ? money(row.rate) + "/hr" : NONE),
  },
  { key: "rateSourceLabel", label: "Rate source", align: "left", render: (row) => row.rateSourceLabel || NONE },
  {
    key: "adjustedHours", label: "Adj. hours", align: "right",
    render: (row) => (row.adjustedHours != null ? row.adjustedHours.toFixed(2) : NONE),
  },
  {
    key: "laborCost", label: "Labor cost", align: "right",
    render: (row) => (row.laborCost != null ? money(row.laborCost) : NONE),
  },
];
