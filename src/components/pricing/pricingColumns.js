/* ============================================================
   pricingColumns.js — what the Material Pricing workspace shows.
   Mirrors the data-driven shape: the header row and the body read
   one list rather than two that can drift.

   Rows come from store.getMaterialRows (Task 9's mapMaterialRow),
   one row per takeoff item, resolved fresh on every read through the
   precedence chain. unitPrice is independently nullable.
   ============================================================ */

const NONE = "—";
const money = (n) => "$" + Number(n).toFixed(2);

export const COLUMNS = [
  { key: "itemName", label: "Material", align: "left", render: (row) => row.itemName },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "unitPrice",
    label: "Unit price",
    align: "right",
    render: (row) => (row.unitPrice != null ? money(row.unitPrice) : NONE),
  },
  { key: "sourceLabel", label: "Source", align: "left", render: (row) => row.sourceLabel || NONE },
];
