/* ============================================================
   SampleBanner.jsx — the honesty label on a demo project's takeoff.

   Seed mode has no ingestion engine, so a project walked through the
   upload/processing flow gets a copy of the fixture takeoff stood in for
   it (seed.js's attachSampleTakeoff). This banner states that plainly
   wherever that takeoff is reviewed, so a sampled quantity is never
   mistaken for one derived from the estimator's own drawings -- the one
   thing the review workspace must never imply. Rendered only when the
   project row carries `sample: true`.
   ============================================================ */

import { Info } from "lucide-react";

export default function SampleBanner() {
  return (
    <div className="sample-banner" role="note">
      <Info aria-hidden="true" size={16} />
      <p>
        <strong>Sample takeoff.</strong> This project shows sample data for demonstration — it isn't derived from your
        uploaded documents.
      </p>
    </div>
  );
}
