/* ============================================================
   EstimateSummary.jsx — the ROM estimate workspace.

   A document rather than a workspace, which is the point: an estimator
   opens this to hand a general contractor a number before the evidence
   for every line exists. Structurally it mirrors the approved mockup at
   docs/specs/assets/rom-mockup.html.

   There is no approval control anywhere on this screen, and that is
   deliberate rather than unbuilt. A ROM is not a bid; approval is the
   gate on the committed number and lives in the review workspace and
   on Export, which this screen does not touch. The qualifications block
   is what carries the weight approval carries there — see the footer
   copy in estimateCopy.js.
   ============================================================ */

import EstimateSection from "./EstimateSection.jsx";
import QualificationsBlock from "./QualificationsBlock.jsx";
import { COPY, dollars, rangeNote } from "./estimateCopy.js";
import { downloadRom } from "./romDownload.js";
import { useEstimate } from "./useEstimate.js";

export default function EstimateSummary() {
  const { estimate, loadError, overrideLine } = useEstimate();

  if (loadError) {
    return (
      <div className="est-wrap">
        <p className="est-error" role="alert">
          {loadError}
        </p>
      </div>
    );
  }

  if (!estimate) {
    return (
      <div className="est-wrap">
        <p className="est-loading">{COPY.loading}</p>
      </div>
    );
  }

  const { range } = estimate;
  const sameEnds = range.low === range.high;

  return (
    <div className="est-wrap">
      <article className="est-doc">
        <header className="est-head">
          <div className="est-headtop">
            <p className="est-kicker">{COPY.kicker}</p>
            {!estimate.emptyReason && (
              <button type="button" className="btn est-download" onClick={() => downloadRom(estimate)}>
                {COPY.download}
              </button>
            )}
          </div>
          <h1 className="est-ptitle">{estimate.projectName}</h1>
          <p className="est-psub">
            {[
              estimate.revisionSetLabel,
              `${estimate.sheetCount} electrical ${estimate.sheetCount === 1 ? "sheet" : "sheets"}`,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>

          {estimate.pendingReason && (
            <div className="est-pending" role="status">
              <p className="est-pending-head">{COPY.pendingHeading}</p>
              <p className="est-pending-body">{estimate.pendingReason}</p>
            </div>
          )}

          {estimate.emptyReason ? (
            <p className="est-empty">{estimate.emptyReason}</p>
          ) : (
            <div className="est-headrow">
              <p className="est-big tabular">{dollars(estimate.directCost)}</p>
              <p className="est-bignote">
                {!sameEnds && (
                  <>
                    {COPY.rangeLabel}{" "}
                    <b className="tabular">
                      {dollars(range.low)} – {dollars(range.high)}
                    </b>
                    .{" "}
                  </>
                )}
                {rangeNote(estimate)}
                {estimate.unpricedCount > 0 && (
                  <>
                    {" "}
                    <b>
                      {estimate.unpricedCount}{" "}
                      {estimate.unpricedCount === 1 ? "line carries" : "lines carry"} no price and
                      {estimate.unpricedCount === 1 ? " is" : " are"} not in this number.
                    </b>
                  </>
                )}
              </p>
            </div>
          )}
        </header>

        {estimate.sections.map((section, i) => (
          <EstimateSection key={section.key} index={i + 1} section={section} onOverride={overrideLine} />
        ))}

        <QualificationsBlock qualifications={estimate.qualifications} />

        <footer className="est-foot">{COPY.footer}</footer>
      </article>
    </div>
  );
}
