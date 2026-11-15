/* ============================================================
   EstimateSection.jsx — one numbered section of the ROM document.

   Origin is never colour alone: every row carries the word "Counted" or
   "Assumed" in its tag, and an assumed row additionally carries a
   dashed left edge. Two redundant channels, so the distinction survives
   a grayscale print and a colour-vision difference — the same rule the
   four review labels follow, applied to a different axis.
   ============================================================ */

import OverrideBox from "./OverrideBox.jsx";
import { ORIGIN, COPY, dollars } from "./estimateCopy.js";

function Amount({ line }) {
  // null is "nothing priced this", 0 is "somebody priced it at nothing".
  // Collapsing them would print $0 over a line nobody costed, which is
  // the confidently wrong number this whole document exists to avoid.
  if (line.amount == null) {
    if (line.origin === "assumed" && line.basis === "standard_exclusion") return <span>—</span>;
    return (
      <span className="est-unpriced" title={COPY.notPricedTitle}>
        {COPY.notPriced}
      </span>
    );
  }
  const amount = dollars(line.amount);
  if (line.basis === "standard_exclusion") {
    return (
      <span className="tabular est-removed" title={`${amount} ${COPY.excludedLabel}`}>
        −{amount}
      </span>
    );
  }
  return <span className="tabular">{amount}</span>;
}

function Value({ line }) {
  if (!line.value) return null;
  return (
    <span className="est-value tabular">
      {line.value}
      {line.unit ? ` ${line.unit}` : ""}
    </span>
  );
}

export default function EstimateSection({ index, section, onOverride }) {
  const origin = (line) => ORIGIN[line.origin] || ORIGIN.counted;

  return (
    <section className="est-section" aria-labelledby={`est-section-${section.key}`}>
      <header className="est-sechead">
        <h2 className="est-secname" id={`est-section-${section.key}`}>
          <span className="est-secnum tabular">{index}</span> {section.label}
        </h2>
        <p className="est-tally">
          <b className="tabular">{section.countedCount}</b> read from documents ·{" "}
          <b className="tabular">{section.assumedCount}</b> assumed
        </p>
      </header>

      {section.lines.length === 0 ? (
        <p className="est-sec-empty">Nothing in this section yet.</p>
      ) : (
        <table className="est-table">
          <caption className="sr-only">
            {section.label} — {section.countedCount} read from documents, {section.assumedCount} assumed
          </caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">Line</th>
              <th scope="col">Origin</th>
              <th scope="col">Quantity</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {section.lines.map((line, i) => (
              <tr key={line.id || `${section.key}-${i}`} className={`est-row est-${line.origin}`}>
                <td className="est-first">
                  <span className="est-title">{line.title}</span>
                  {(line.found || line.where) && (
                    <span className="est-src">
                      {line.found}
                      {line.basisLabel ? ` — ${line.basisLabel}.` : ""}
                      {line.where ? ` ${line.where}` : ""}
                    </span>
                  )}
                </td>
                <td className="est-origin">
                  <span className={`est-tag est-tag-${line.origin}`} title={origin(line).title}>
                    {origin(line).label}
                  </span>
                  {line.id && onOverride && (line.origin === "assumed" || line.source === "estimator") && (
                    <OverrideBox line={line} onOverride={onOverride} />
                  )}
                </td>
                <td className="est-qty">
                  <Value line={line} />
                </td>
                <td className="est-amt">
                  <Amount line={line} />
                </td>
              </tr>
            ))}
            {section.subtotal != null && (
              <tr className="est-subtot">
                <td className="est-first">
                  {COPY.subtotalLabel} — {section.label.toLowerCase()}
                </td>
                <td />
                <td />
                <td className="est-amt tabular">{dollars(section.subtotal)}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}
