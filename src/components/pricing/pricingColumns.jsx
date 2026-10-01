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

   Basis now also carries the market-pricing tiers (Market estimate,
   Supplier quote) alongside the existing resolved tiers (Company
   price, Regional baseline) and the two entry kinds above -- all of
   them render as `.pill--tier`, a slate tag distinct from the four
   status-pill colors (CLAUDE.md), never the plain `.pill--neutral`
   marker used elsewhere for a non-tier badge. A Supplier quote row
   also names the supplier, since that is the one tier a person, not a
   lookup, provided.

   A market-priced row additionally carries a warning (row-warning,
   under the basis note) when the row couldn't be priced, and its
   sellers/matched-item evidence as a details element -- both render
   in the Material cell so they travel with the item they describe.
   ============================================================ */

import Pill from "../Pill.jsx";
import { STATUS, STATUS_ORDER } from "../../lib/vocabulary.js";

export const NONE = "—";
export const money = (n) => "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const BASIS_LABEL = { project_price: "Project price", allowance: "Allowance" };

export const ALLOWANCE_REASON_MESSAGE =
  "An allowance needs a reason — say what it's standing in for, so the total can be traced back.";

/** Market evidence is either a list of sellers (Google Shopping's
 *  listings, `{seller, price, link}` each) or the one matched catalog
 *  item 1build returns (`{name, uom}`, with no price of its own to show
 *  -- the row's unit price is that item's rate). Either shape is written
 *  by a market source, not the estimator, so seller/item names render
 *  as text nodes only -- never markup. */
function MarketEvidence({ evidence }) {
  const isSellers = "seller" in evidence[0];
  return (
    <details className="market-evidence">
      <summary>{isSellers ? "Sellers" : "Matched item"}</summary>
      <ul>
        {evidence.map((e, i) => {
          const text = isSellers ? (
            <>
              {e.seller} — <span className="tabular">{money(e.price)}</span>
            </>
          ) : (
            <>
              {e.name}
              {e.uom ? ` — ${e.uom}` : ""}
            </>
          );
          return <li key={i}>{isSellers && e.link ? <a href={e.link} target="_blank" rel="noreferrer">{text}</a> : text}</li>;
        })}
      </ul>
    </details>
  );
}

export const COLUMNS = [
  {
    key: "status", label: "Status", align: "left", render: (row) => <Pill status={row.status} />,
    text: (row) => STATUS[row.status]?.label ?? "", sortValue: (row) => STATUS_ORDER.indexOf(row.status),
  },
  {
    key: "itemName", label: "Material", align: "left", header: true,
    render: (row) => (
      <>
        {row.itemName}
        {row.basisNote ? <div className="muted">{row.basisNote}</div> : null}
        {row.marketWarning ? (
          <div className="row-warning">
            <strong>{row.marketWarning.title}</strong> {row.marketWarning.fix}
          </div>
        ) : null}
        {row.marketEvidence && row.marketEvidence.length > 0 ? <MarketEvidence evidence={row.marketEvidence} /> : null}
      </>
    ),
    text: (row) => row.itemName, sortValue: (row) => row.itemName,
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
    key: "range", label: "Range", align: "right",
    render: (row) => (row.priceLow != null && row.priceHigh != null && row.priceLow !== row.priceHigh
      ? <span className="tabular">{money(row.priceLow)}–{money(row.priceHigh)}</span> : NONE),
    text: (row) => (row.priceLow != null && row.priceHigh != null ? `${row.priceLow}–${row.priceHigh}` : ""),
    sortValue: (row) => row.priceLow ?? null,
  },
  {
    key: "source", label: "Basis", align: "left",
    className: (row) => (row.pendingSource ? "is-pending" : undefined),
    render: (row) => {
      const label = row.pendingSource ? BASIS_LABEL[row.pendingSource] : row.sourceLabel;
      if (!label) return NONE;
      return (
        <span className="pill pill--tier">
          {label}
          {row.sourceLabel === "Supplier quote" && row.supplierName ? ` — ${row.supplierName}` : null}
        </span>
      );
    },
    text: (row) => row.sourceLabel ?? "", sortValue: (row) => row.sourceLabel ?? null,
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
    text: (row) => (row.unitPrice != null ? String(Number(row.quantity) * Number(row.unitPrice)) : ""),
    sortValue: (row) => (row.unitPrice != null ? Number(row.quantity) * Number(row.unitPrice) : null),
  },
];
