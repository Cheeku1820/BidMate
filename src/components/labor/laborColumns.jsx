/* ============================================================
   laborColumns.jsx — what the Labor workspace shows and which cells
   edit (docs/specs/pricing-grid.md, "The two screens → Labor").
   Header and body read one list, as before; `edit` is what DataGrid
   reads to make a cell typeable, and `hasEntry` is what lets it be
   cleared back to the next source.

   Rows come from store.getLaborRows, one per takeoff item, resolved
   fresh through the precedence chain in
   docs/specs/labor-material-pricing.md. hoursPerUnit / rate /
   adjustedHours / laborCost are independently nullable, so every
   numeric cell falls back to NONE rather than a fabricated 0.
   ============================================================ */

import Pill from "../Pill.jsx";
import { STATUS, STATUS_ORDER } from "../../lib/vocabulary.js";

export const NONE = "—";
export const money = (n) => "$" + Math.round(Number(n)).toLocaleString();
export const money2 = (n) => "$" + Number(n).toFixed(2);
const percent = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(Number(n)).toLocaleString() + "%";

export const COLUMNS = [
  {
    key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} />,
    text: (row) => STATUS[row.status]?.label ?? "", sortValue: (row) => STATUS_ORDER.indexOf(row.status),
  },
  {
    key: "itemName", label: "Item", align: "left", header: true,
    render: (row) => (
      <>
        {row.itemName}
        {row.basisNote ? <div className="muted">{row.basisNote}</div> : null}
      </>
    ),
    text: (row) => row.itemName, sortValue: (row) => row.itemName,
  },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "hoursPerUnit", label: "Hours/unit", align: "right",
    render: (row) => (row.hoursPerUnit != null ? Number(row.hoursPerUnit).toFixed(3) : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Hours can't be negative",
      value: (row) => row.hoursPerUnit,
      hasEntry: (row) => row.hoursSourceLabel === "Estimator entered",
    },
  },
  {
    key: "hoursSourceLabel", label: "Hours source", align: "left",
    render: (row) => (row.hoursSourceLabel ? <span className="pill pill--neutral">{row.hoursSourceLabel}</span> : NONE),
    text: (row) => row.hoursSourceLabel ?? "",
  },
  {
    key: "rate", label: "Rate", align: "right",
    render: (row) => (row.rate != null ? money2(row.rate) + "/hr" : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Rate can't be negative",
      value: (row) => row.rate,
      hasEntry: (row) => row.rateSourceLabel === "Estimator entered",
    },
  },
  {
    key: "rateSourceLabel", label: "Rate source", align: "left",
    render: (row) => (row.rateSourceLabel ? <span className="pill pill--neutral">{row.rateSourceLabel}</span> : NONE),
    text: (row) => row.rateSourceLabel ?? "",
  },
  {
    key: "adjustmentPercent", label: "Adjustment", align: "right",
    render: (row) => (row.adjustmentPercent != null ? percent(row.adjustmentPercent) : NONE),
    edit: {
      kind: "number", min: -100, minMessage: "Adjustment can't be below −100%",
      value: (row) => row.adjustmentPercent,
      hasEntry: (row) => row.adjustmentPercent != null,
    },
  },
  {
    key: "adjustmentReason", label: "Adjustment reason", align: "left",
    render: (row) => row.adjustmentReason || NONE,
    edit: { kind: "text", value: (row) => row.adjustmentReason, hasEntry: (row) => Boolean(row.adjustmentReason) },
  },
  {
    key: "adjustedHours", label: "Adj. hours", align: "right",
    render: (row) => (row.adjustedHours != null ? Number(row.adjustedHours).toFixed(2) : NONE),
  },
  {
    key: "laborCost", label: "Labor cost", align: "right",
    render: (row) => (row.laborCost != null ? money(row.laborCost) : NONE),
  },
];

/** What each editable column sends on the wire, and what its toast says. */
export const FIELDS = {
  // Three places, matching the cell, so 0.125 toasts as "0.125".
  hoursPerUnit: { wire: "hoursOverride", noun: "hours", format: (v) => Number(v).toFixed(3).replace(/\.?0+$/, "") },
  rate: { wire: "rateOverride", noun: "rate", format: (v) => money2(v) + "/hr" },
  adjustmentPercent: { wire: "adjustmentPercent", noun: "adjustment", format: (v) => percent(v) },
  adjustmentReason: { wire: "adjustmentReason", noun: "adjustment reason", format: null },
};
