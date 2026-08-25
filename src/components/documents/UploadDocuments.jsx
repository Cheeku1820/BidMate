/* ============================================================
   UploadDocuments.jsx — spec §5 screen C, the intake path.

   Seed mode has no ingestion engine, so nothing here is parsed for real
   -- files are held in component state only, never uploaded anywhere,
   and "Start takeoff" hands off to the processing screen, which stands
   in a sample takeoff (see ProcessingStatus.jsx and seed.js's
   attachSampleTakeoff). What this screen does carry honestly is the full
   set of intake states spec §10 requires: uploading, uploaded, a
   duplicate a file matches, an unsupported file type, and a
   password-protected file -- each stated in plain language with a
   recovery action, never a bare "something went wrong".

   The document-type dropdown is editable per spec §5: the estimator, not
   a detector, says what each file is.
   ============================================================ */

import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { FileText, Upload, X } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";

const DOC_TYPES = ["Drawings", "Specifications", "Addendum", "Scope", "Other"];

// A file is "ready" (counts toward starting a takeoff) only when it
// uploaded cleanly. The other four are the spec §10 states, each with
// its own copy below.
const STATE_COPY = {
  uploading: "Uploading…",
  ready: "Uploaded",
  duplicate: "Already added — remove one copy",
  unsupported: "Not a PDF — upload the drawing set as a PDF",
  protected: "Password protected — upload an unlocked copy",
};

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Classifies a freshly-added file into one of the intake states. Real
// ingestion would open the file; here the checks are deliberately shallow
// stand-ins (extension, name), enough to exercise every §10 state without
// a parser.
function classify(file, existing) {
  const lower = file.name.toLowerCase();
  if (existing.some((f) => f.name === file.name && f.size === file.size)) return "duplicate";
  if (!lower.endsWith(".pdf")) return "unsupported";
  if (lower.includes("protected") || lower.includes("locked")) return "protected";
  return "uploading";
}

export default function UploadDocuments() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [dragging, setDragging] = useState(false);

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList);
    setFiles((prev) => {
      let next = prev;
      for (const file of incoming) {
        const status = classify(file, next);
        const entry = {
          id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
          name: file.name,
          size: file.size,
          docType: DOC_TYPES[0],
          status,
        };
        next = [...next, entry];
        // A cleanly-uploading file settles to "ready" after a beat, the
        // way a real upload would confirm. Guarded to this entry's id so
        // a later remove can't resurrect it.
        if (status === "uploading") {
          const settleId = entry.id;
          setTimeout(() => {
            setFiles((cur) => cur.map((f) => (f.id === settleId && f.status === "uploading" ? { ...f, status: "ready" } : f)));
          }, 700);
        }
      }
      return next;
    });
  };

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
  };

  const removeFile = (id) => setFiles((prev) => prev.filter((f) => f.id !== id));
  const setDocType = (id, docType) => setFiles((prev) => prev.map((f) => (f.id === id ? { ...f, docType } : f)));

  const readyCount = files.filter((f) => f.status === "ready").length;

  const startTakeoff = () => {
    if (readyCount === 0) return;
    navigate(`/projects/${projectId}/processing`);
  };

  return (
    <>
      <AppTopBar
        title="Documents"
        primaryAction={
          <button type="button" className="btn btn--primary" disabled={readyCount === 0} onClick={startTakeoff}>
            Start takeoff
          </button>
        }
      />
      <ProjectNav projectId={projectId} />

      <div className="page">
        <h1 className="page-heading">Upload documents</h1>
        <p className="muted">
          Add the drawing set, specifications, addenda, and scope documents as PDFs. You can change what each file is
          after it uploads.
        </p>

        <div
          className={dragging ? "dropzone is-dragging" : "dropzone"}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <Upload aria-hidden="true" size={28} />
          <p>Drag PDF files here</p>
          <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
            Choose files
          </button>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            multiple
            className="sr-only"
            onChange={(event) => {
              addFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </div>

        {files.length === 0 ? (
          <p className="muted">No files added yet.</p>
        ) : (
          <table className="data-table upload-table">
            <thead>
              <tr>
                <th scope="col">File</th>
                <th scope="col">Type</th>
                <th scope="col">Size</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => (
                <tr key={file.id}>
                  <th scope="row" className="upload-name">
                    <FileText aria-hidden="true" size={16} />
                    {file.name}
                  </th>
                  <td>
                    <label className="sr-only" htmlFor={`doctype-${file.id}`}>
                      Document type for {file.name}
                    </label>
                    <select
                      id={`doctype-${file.id}`}
                      className="field field--compact"
                      value={file.docType}
                      onChange={(event) => setDocType(file.id, event.target.value)}
                    >
                      {DOC_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="tabular">{formatSize(file.size)}</td>
                  <td>
                    <span className={`upload-status upload-status--${file.status}`}>{STATE_COPY[file.status]}</span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="iconbtn"
                      aria-label={`Remove ${file.name}`}
                      onClick={() => removeFile(file.id)}
                    >
                      <X aria-hidden="true" size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="form-actions">
          <button type="button" className="btn btn--primary" disabled={readyCount === 0} onClick={startTakeoff}>
            Start takeoff
          </button>
          <Link className="btn" to={`/projects/${projectId}`}>
            Save and exit
          </Link>
        </div>
      </div>
    </>
  );
}
