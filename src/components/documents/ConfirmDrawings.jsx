/* ============================================================
   ConfirmDrawings.jsx — spec §5 screen D, "confirm detected
   information".

   Sits between upload and processing. It reflects the actual uploaded
   set (from uploadedFiles): the drawing files that will run through the
   takeoff, and the specifications/addenda that are read as context. Two
   things the estimator confirms before processing, surfaced in a Needs
   attention section ABOVE the table rather than buried in a row (spec §5):
   documents whose type wasn't recognized, and whether a drawing set is
   present at all. Types stay editable here, and any file can be excluded.

   Sheet-level detail (revisions, per-sheet scale) is detected when the
   engine reads the drawings, so it belongs to processing, not this
   pre-processing confirmation.
   ============================================================ */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, FileText } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";
import { getUploadedFiles, setUploadedFiles } from "../../lib/uploadedFiles.js";
import { DOC_TYPES } from "../../lib/detectDocType.js";

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ConfirmDrawings() {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [rows, setRows] = useState(() =>
    getUploadedFiles(projectId).map((f, i) => ({
      id: i,
      name: f.file?.name ?? `document ${i + 1}`,
      size: f.file?.size ?? 0,
      docType: f.docType,
      file: f.file,
      included: true,
    })),
  );

  const setType = (id, docType) => setRows((prev) => prev.map((r) => (r.id === id ? { ...r, docType } : r)));
  const toggle = (id) => setRows((prev) => prev.map((r) => (r.id === id ? { ...r, included: !r.included } : r)));

  const kept = rows.filter((r) => r.included);
  const counts = kept.reduce((acc, r) => ({ ...acc, [r.docType]: (acc[r.docType] || 0) + 1 }), {});
  const drawings = kept.filter((r) => r.docType === "Drawings");
  const unrecognized = kept.filter((r) => r.docType === "Other");
  const hasDrawings = drawings.length > 0;

  const start = () => {
    if (!hasDrawings) return;
    setUploadedFiles(
      projectId,
      kept.map((r) => ({ file: r.file, docType: r.docType })),
    );
    navigate(`/projects/${projectId}/processing`);
  };

  if (rows.length === 0) {
    return (
      <>
        <AppTopBar title="Confirm documents" />
        <ProjectNav projectId={projectId} />
        <div className="empty-state">
          <h2>No documents to confirm</h2>
          <p>Add the drawing set and its documents first.</p>
          <Link className="btn btn--primary" to={`/projects/${projectId}/documents`}>
            Upload documents
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <AppTopBar
        title="Confirm documents"
        primaryAction={
          <button type="button" className="btn btn--primary" disabled={!hasDrawings} onClick={start}>
            Start takeoff
          </button>
        }
      />
      <ProjectNav projectId={projectId} />

      <div className="page">
        <h1 className="page-heading">Confirm detected documents</h1>
        <p className="muted">
          Drawings run through the takeoff; specifications and addenda are read as context. Correct any type, or leave a
          document out, before processing.
        </p>

        <div className="card-grid">
          <section className="card">
            <h2>Drawings</h2>
            <p className="tabular">{counts.Drawings || 0}</p>
            <p className="muted">Run through the takeoff</p>
          </section>
          <section className="card">
            <h2>Specifications</h2>
            <p className="tabular">{counts.Specifications || 0}</p>
            <p className="muted">Read for schedules and requirements</p>
          </section>
          <section className="card">
            <h2>Addenda</h2>
            <p className="tabular">{counts.Addendum || 0}</p>
            <p className="muted">Read for changes</p>
          </section>
          <section className="card">
            <h2>Other</h2>
            <p className="tabular">{counts.Other || 0}</p>
            <p className="muted">Read as context</p>
          </section>
        </div>

        {!hasDrawings ? (
          <div className="warncard warncard--missing" role="alert">
            <h4>
              <AlertTriangle aria-hidden="true" size={16} /> No drawing set
            </h4>
            <p>
              The takeoff needs at least one document typed <strong>Drawings</strong>. Set one below, or go back and add
              the drawing set.
            </p>
          </div>
        ) : null}

        {unrecognized.length > 0 ? (
          <div className="warncard warncard--attention" role="status">
            <h4>
              <AlertTriangle aria-hidden="true" size={16} />{" "}
              {unrecognized.length === 1
                ? "1 document wasn't recognized"
                : `${unrecognized.length} documents weren't recognized`}
            </h4>
            <p>
              {unrecognized.map((r) => r.name).join(", ")} — confirm the type so {unrecognized.length === 1 ? "it is" : "they are"}{" "}
              read correctly, or leave as Other to include as plain context.
            </p>
          </div>
        ) : null}

        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">
                <span className="sr-only">Include</span>
              </th>
              <th scope="col">Document</th>
              <th scope="col">Type</th>
              <th scope="col">Size</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={r.included ? undefined : "is-excluded"}>
                <td>
                  <input type="checkbox" aria-label={`Include ${r.name}`} checked={r.included} onChange={() => toggle(r.id)} />
                </td>
                <th scope="row" className="upload-name">
                  <FileText aria-hidden="true" size={16} />
                  {r.name}
                </th>
                <td>
                  <label className="sr-only" htmlFor={`confirm-type-${r.id}`}>
                    Type for {r.name}
                  </label>
                  <select
                    id={`confirm-type-${r.id}`}
                    className="field field--compact"
                    value={r.docType}
                    disabled={!r.included}
                    onChange={(e) => setType(r.id, e.target.value)}
                  >
                    {DOC_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="tabular">{formatSize(r.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="form-actions">
          <button type="button" className="btn btn--primary" disabled={!hasDrawings} onClick={start}>
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
