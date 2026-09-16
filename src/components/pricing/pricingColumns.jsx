/* ============================================================
   pricingColumns.jsx — what the Material pricing workspace shows and
   which cells edit (docs/specs/pricing-grid.md, "The two screens →
   Material pricing").

   Basis is the one cell that is sometimes read-only and sometimes a
   select, and the rule is the row's `source`: with no project entry
   yet it shows the resolved tier (Company price, Regional baseline)
   and cannot be edited -- typing a price is what creates an entry;
   with one, it is a select between the two things an entry can mean.
   Reason follows Basis. Neither can be cleared on its own: the price
   is the entry, and clearing it clears all three.

   `pendingSource` is set by the screen while an Allowance choice waits
   on its reason -- rendered as the tag it will become, dashed, so the
   row shows what is about to happen without pretending it has.
   ============================================================ */

import Pill from "../Pill.jsx";

export const NONE = "—";
export const money = (n) => "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const BASIS_LABEL = { project_price: "Project price", allowance: "Allowance" };

export const ALLOWANCE_REASON_MESSAGE =
  "An allowance needs a reason — say what it's standing in for, so the total can be traced back.";

export const COLUMNS = [
  { key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} /> },
  {
    key: "itemName", label: "Material", align: "left", header: true,
    render: (row) => (
      <>
        {row.itemName}
        {row.basisNote ? <div className="muted">{row.basisNote}</div> : null}
      </>
    ),
  },
  { key: "quantity", label: "Quantity", align: "right", render: (row) => row.quantity },
  {
    key: "unitPrice", label: "Unit price", align: "right",
    render: (row) => (row.unitPrice != null ? money(row.unitPrice) : NONE),
    edit: {
      kind: "number", min: 0, minMessage: "Price can't be negative",
      value: (row) => row.unitPrice,
      hasEntry: (row) => row.source != null,
    },
  },
  {
    key: "source", label: "Basis", align: "left",
    className: (row) => (row.pendingSource ? "is-pending" : undefined),
    render: (row) => {
      const label = row.pendingSource ? BASIS_LABEL[row.pendingSource] : row.sourceLabel;
      return label ? <span className="pill pill--neutral">{label}</span> : NONE;
    },
    edit: {
      kind: "select",
      value: (row) => row.pendingSource || row.source,
      options: [
        { value: "project_price", label: "Project price" },
        { value: "allowance", label: "Allowance" },
      ],
      disabled: (row) => row.source == null,
    },
  },
  {
    key: "reason", label: "Reason", align: "left",
    render: (row) => row.reason || NONE,
    edit: {
      kind: "text",
      value: (row) => row.reason,
      disabled: (row) => row.source == null,
      required: (row) => (row.pendingSource || row.source) === "allowance",
      requiredMessage: ALLOWANCE_REASON_MESSAGE,
    },
  },
  {
    key: "lineTotal", label: "Line total", align: "right",
    render: (row) => (row.unitPrice != null ? money(Number(row.quantity) * Number(row.unitPrice)) : NONE),
  },
];
