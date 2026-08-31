/* ============================================================
   PlanDrawing.jsx — the base layer under the takeoff markers.

   Every sheet in this product comes from an uploaded document, and this
   renders the honest surface for that case: blank paper with just the
   sheet number, because there is no drawn geometry that could stand in
   for a page nobody in this codebase has seen.

   Sheet space is 1000 x 750 units for every plan.
   ============================================================ */

const DIM = "#8a857c";

/** Deliberately empty apart from the sheet's own number and title:
 *  a fabricated plan under a real takeoff would read as the estimator's
 *  own drawing, and nobody in this codebase has seen the actual page to
 *  draw honestly. The only text here comes from the sheet record itself. */
function IngestedSheetSurface({ sheet }) {
  return (
    <g>
      <text x="500" y="374" fill={DIM} fontSize="12" textAnchor="middle">
        {sheet.number}
        {sheet.title ? ` — ${sheet.title}` : ""}
      </text>
    </g>
  );
}

export default function PlanDrawing({ sheet }) {
  // Every sheet that came from an uploaded document gets the neutral
  // surface below -- there is no drawn geometry that could honestly
  // stand in for a page nobody in this codebase has seen. `plan` is
  // always "" for a real, ingested sheet (see ingest.py); the two
  // fixture floor plans this function used to branch to for
  // sheet.plan === "warehouse"/"office" were seed-store-only and are
  // gone along with the seed store.
  return <IngestedSheetSurface sheet={sheet} />;
}
