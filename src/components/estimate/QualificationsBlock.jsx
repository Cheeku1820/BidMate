/* ============================================================
   QualificationsBlock.jsx — the condition of the price.

   Generated from the assumed lines above it, never typed. This is the
   part of the document a general contractor actually reads, and a
   qualifications list that can disagree with the sections it summarizes
   would be worse than none — which is why it comes down from the server
   already deduped and ordered (api/app/estimate/assemble.py) rather
   than being assembled here.
   ============================================================ */

import { COPY, dollars } from "./estimateCopy.js";

export default function QualificationsBlock({ qualifications }) {
  if (!qualifications.length) return null;

  return (
    <section className="est-qual" aria-labelledby="est-qual-title">
      <h2 className="est-qual-title" id="est-qual-title">
        {COPY.qualificationsTitle}
      </h2>
      <p className="est-qual-lead">{COPY.qualificationsLead}</p>
      <ol className="est-qual-list">
        {qualifications.map((q, i) => (
          <li key={`${q.title}-${i}`}>
            <span className="est-qual-found">
              {q.title}. {q.found} {q.why}
            </span>
            {q.excludedValue ? (
              <span className="est-qual-removed tabular">
                {dollars(q.excludedValue)} {COPY.excludedLabel}.
              </span>
            ) : null}
            <span className="est-qual-where">
              {q.basisLabel}. {q.where}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
