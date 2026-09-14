/* ============================================================
   spreadsheetColumns.js — what the takeoff table shows.

   Data-driven so the header row, the body, and the column-visibility
   control read one list rather than three that can drift.

   Spec §10.1 lists thirteen columns. Four of them -- manufacturer/model
   requirement, waste factor, floor/area, and specification reference --
   have no field anywhere in the item model, and one more (last edited
   by) lives in the action log rather than the snapshot. They are absent
   here rather than rendered empty: a blank cell under "Waste factor"
   does not read as "not built yet", it reads as "no waste applied",
   which is a fabricated fact about the estimator's own numbers. Waste
   in particular has a settled meaning in docs/mvp-approach.md §4.1 --
   store the measured quantity and the factor separately, derive the
   purchase quantity at the point of use -- that a column here would
   prejudge.
   ============================================================ */

import { STATUS } from "../../lib/vocabulary.js";

/** The absent-value mark. A dash reads as "nothing here" where an empty
 *  cell reads as an oversight. */
const NONE = "—";

const money = (n) => "$" + Math.round(Number(n)).toLocaleString();

export const COLUMNS = [
  {
    key: "status",
    label: "Status",
    align: "left",
    // Rendered by the table itself rather than here: status needs an
    // icon and a hue alongside the text (never colour alone), which is
    // markup rather than a string.
    render: (item) => STATUS[item.status]?.label ?? item.status,
  },
  { key: "name", label: "Item", align: "left", render: (item) => item.name },
  { key: "description", label: "Description", align: "left", render: (item) => item.description || NONE },
  { key: "system", label: "System", align: "left", render: (item) => item.system || NONE },
  {
    key: "quantity",
    label: "Quantity",
    align: "right",
    render: (item) => `${item.quantity} ${item.unit}`.trim(),
  },
  {
    key: "approvedQuantity",
    label: "Approved quantity",
    align: "right",
    // Only an approved item has an approved quantity. Showing the raw
    // quantity here for an unapproved row would put a number under an
    // "Approved" heading that nobody has confirmed.
    render: (item) => (item.status === "approved" ? `${item.quantity} ${item.unit}`.trim() : NONE),
  },
  {
    key: "sheet",
    label: "Sheet",
    align: "left",
    render: (item, { sheetsById }) => sheetsById[item.sheetId]?.number ?? NONE,
  },
  { key: "notes", label: "Notes", align: "left", render: (item) => item.notes || NONE },
  // Cost columns are populated only for a priced takeoff. An item the
  // pricing step never reached carries zero, and zero is not a price --
  // it shows a dash rather than a fabricated $0, the same absent-vs-empty
  // rule the columns above follow.
  {
    key: "materialCost",
    label: "Material",
    align: "right",
    render: (item) => (item.materialCost ? money(item.materialCost) : NONE),
  },
  {
    key: "laborHours",
    label: "Labor hrs",
    align: "right",
    render: (item) => (item.laborHours ? item.laborHours : NONE),
  },
  {
    key: "totalCost",
    label: "Total",
    align: "right",
    render: (item) => (item.totalCost ? money(item.totalCost) : NONE),
  },
];

/** Description and notes are long and push the numeric columns off the
 *  visible width at 1280px, so they start hidden and can be switched on.
 *  Everything else starts visible. */
export const DEFAULT_VISIBLE = new Set(
  COLUMNS.map((c) => c.key).filter((key) => key !== "description" && key !== "notes"),
);
