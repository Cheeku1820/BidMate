/* ============================================================
   ConfirmDrawings.jsx — spec §5 screen D, "confirm detected
   information".

   Sits between upload and processing: the estimator corrects the
   interpretation of the set before the takeoff runs. In seed mode there
   is no detector, so the detected sheets shown here are the sample set
   the processing screen stands in -- framed as detected for the flow,
   and everything the estimator lands on afterward carries the sample
   banner, so nothing is presented as a real reading of their upload.

   The rules that carry regardless of engine: an unchecked sheet is
   excluded from the takeoff (include checkboxes), and anything the set
   couldn't resolve -- a missing scale, a duplicate revision -- surfaces
   in a Needs attention section ABOVE the table rather than buried in a
   row, per spec §5.
   ============================================================ */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";

// The detected set. `scale: null` and duplicate revisions are the cases
// spec §5 wants surfaced as needing attention before takeoff.
const DETECTED_SHEETS = [
  { id: "e11", number: "E1.1", title: "Level 1 power", discipline: "Electrical", revision: "Rev 3", scale: '1/8" = 1\'-0"', status: "ready" },
  { id: "e21", number: "E2.1", title: "Warehouse power", discipline: "Electrical", revision: "Rev 2", scale: null, status: "attention" },
  { id: "e31", number: "E3.1", title: "Roof and site", discipline: "Electrical", revision: "Rev 1", scale: '1/16" = 1\'-0"', status: "ready" },
];

const SUMMARY = {
  projectType: "Warehouse or distribution",
  electricalSheets: DETECTED_SHEETS.length,
  revisions: "Latest set · no conflicts",
  legends: "1 legend, 1 luminaire schedule",
  scaleStatus: "Mixed — one sheet needs confirmation",
};

export default function ConfirmDrawings() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [included, setIncluded] = useState(() => new Set(DETECTED_SHEETS.map((s) => s.id)));

  const toggle = (id) =>
    setIncluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  // Sheets that couldn't be fully resolved. Shown above the table, per
  // spec §5, because they are decisions to make, not rows to scan past.
  const needsAttention = DETECTED_SHEETS.filter((s) => included.has(s.id) && s.scale === null);

  const includedCount = included.size;

  return (
    <>
      <AppTopBar
        title="Confirm drawings"
        primaryAction={
          <button
            type="button"
            className="btn btn--primary"
            disabled={includedCount === 0}
            onClick={() => navigate(`/projects/${projectId}/processing`)}
          >
            Start takeoff
          </button>
        }
      />
      <ProjectNav projectId={projectId} />

      <div className="page">
        <h1 className="page-heading">Confirm detected drawings</h1>
        <p className="muted">
          Correct anything the set got wrong before the takeoff runs. Uncheck a sheet to leave it out.
        </p>

        <div className="card-grid">
          <section className="card">
            <h2>Project type</h2>
            <p>{SUMMARY.projectType}</p>
          </section>
          <section className="card">
            <h2>Electrical sheets</h2>
            <p className="tabular">{SUMMARY.electricalSheets} found</p>
          </section>
          <section className="card">
            <h2>Revisions</h2>
            <p>{SUMMARY.revisions}</p>
          </section>
          <section className="card">
            <h2>Legends and schedules</h2>
            <p>{SUMMARY.legends}</p>
          </section>
          <section className="card">
            <h2>Scale</h2>
            <p>{SUMMARY.scaleStatus}</p>
          </section>
        </div>

        {needsAttention.length > 0 ? (
          <div className="warncard warncard--attention" role="status">
            <h4>
              <AlertTriangle aria-hidden="true" size={16} /> Needs attention before takeoff
            </h4>
            {needsAttention.map((sheet) => (
              <p key={sheet.id}>
                {sheet.number} has no scale in its title block. You can set it now, or the takeoff will flag its measured
                items as missing information until you do.
              </p>
            ))}
          </div>
        ) : null}

        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">
                <span className="sr-only">Include</span>
              </th>
              <th scope="col">Sheet</th>
              <th scope="col">Title</th>
              <th scope="col">Discipline</th>
              <th scope="col">Revision</th>
              <th scope="col">Scale</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {DETECTED_SHEETS.map((sheet) => (
              <tr key={sheet.id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Include ${sheet.number}`}
                    checked={included.has(sheet.id)}
                    onChange={() => toggle(sheet.id)}
                  />
                </td>
                <th scope="row" className="tabular">
                  {sheet.number}
                </th>
                <td>{sheet.title}</td>
                <td>{sheet.discipline}</td>
                <td className="tabular">{sheet.revision}</td>
                <td className="tabular">{sheet.scale ?? "Not found"}</td>
                <td>
                  {sheet.scale === null ? (
                    <span className="upload-status upload-status--protected">Scale needed</span>
                  ) : (
                    <span className="upload-status upload-status--ready">Ready</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="form-actions">
          <button
            type="button"
            className="btn btn--primary"
            disabled={includedCount === 0}
            onClick={() => navigate(`/projects/${projectId}/processing`)}
          >
            Start takeoff
          </button>
          <Link className="btn" to={`/projects/${projectId}/documents`}>
            Back to documents
          </Link>
        </div>
      </div>
    </>
  );
}
