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

   The type tabs filter what the table draws and nothing else. Every
   number on this screen -- the file-state summary, the drawing-set gate
   behind "Review detected drawings", the footer counts -- is computed
   from the whole set, never from the visible rows. This is the same rule
   CLAUDE.md states for the canvas's layer toggles, and for the same
   reason: an estimator narrowing the view to read it must not change
   what the screen is telling them they have.

   No green anywhere in the state column. A cleanly uploaded file is a
   success, but green is reserved for estimator-approved content alone
   (CLAUDE.md) -- blue carries "done, not yet judged".
   ============================================================ */

import { useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, FileText, Upload, X } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { setUploadedFiles } from "../../lib/uploadedFiles.js";
import { DOC_TYPES, detectDocTypeInfo } from "../../lib/detectDocType.js";
import { classifyDoc } from "../../lib/engineClient.js";

// A file is "ready" (counts toward starting a takeoff) only when it
// uploaded cleanly. The other four are the spec §10 states, each with
// its own copy below. `tone` drives the hue; the words are the state, so
// the column never depends on colour to be read.
const STATE_COPY = {
  uploading: { label: "Uploading…", tone: "uploading" },
  ready: { label: "Uploaded", tone: "ready" },
  duplicate: { label: "Already added — remove one copy", tone: "duplicate" },
  unsupported: { label: "Not a PDF — upload the drawing set as a PDF", tone: "unsupported" },
  protected: { label: "Password protected — upload an unlocked copy", tone: "protected" },
};

// The tabs, in the order the mockup lists them: everything, then one per
// document type. Plural display labels ("Addenda") over the stored
// singular value ("Addendum"), which stays what the dropdown writes.
const TABS = [
  { key: "all", label: "All files" },
  { key: "Drawings", label: "Drawings" },
  { key: "Specifications", label: "Specifications" },
  { key: "Addendum", label: "Addenda" },
  { key: "Scope", label: "Scope" },
  { key: "Other", label: "Other" },
];

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
  const [tab, setTab] = useState("all");

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList);
    setFiles((prev) => {
      let next = prev;
      for (const file of incoming) {
        const status = classify(file, next);
        const detected = detectDocTypeInfo(file.name);
        const entry = {
          id: `${file.name}-${file.size}-${crypto.randomUUID()}`,
          name: file.name,
          size: file.size,
          // Pre-select the type from the filename; typeAuto tracks whether
          // it's still the suggestion (shows a "detected" hint) or the
          // estimator has since set it by hand.
          docType: detected.type,
          typeAuto: true,
          status,
          file, // kept so the drawings can be sent to the engine on continue
        };
        next = [...next, entry];
        if (status === "uploading") {
          const settleId = entry.id;
          // A cleanly-uploading file settles to "ready" after a beat, the
          // way a real upload would confirm. Guarded to this entry's id so
          // a later remove can't resurrect it.
          setTimeout(() => {
            setFiles((cur) => cur.map((f) => (f.id === settleId && f.status === "uploading" ? { ...f, status: "ready" } : f)));
          }, 700);
          // When the filename wasn't informative, peek at the content to
          // refine the type -- best-effort, and only if the estimator
          // hasn't set it by hand in the meantime (typeAuto still true).
          if (detected.source === "default") {
            classifyDoc(file).then((type) => {
              if (!type) return;
              setFiles((cur) => cur.map((f) => (f.id === settleId && f.typeAuto ? { ...f, docType: type } : f)));
            });
          }
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
  // A manual change turns off the "detected" hint -- the estimator owns
  // the value now.
  const setDocType = (id, docType) =>
    setFiles((prev) => prev.map((f) => (f.id === id ? { ...f, docType, typeAuto: false } : f)));

  // Derived from `files`, never from the filtered view. See the header.
  const readyCount = files.filter((f) => f.status === "ready").length;
  const uploadingCount = files.filter((f) => f.status === "uploading").length;
  const blockedFiles = files.filter((f) => ["duplicate", "unsupported", "protected"].includes(f.status));
  const drawingsCount = files.filter((f) => f.status === "ready" && f.docType === "Drawings").length;
  // The takeoff runs on the drawing set, so at least one file has to be
  // typed Drawings before there's anything to process.
  const canContinue = drawingsCount > 0;

  const countsByTab = useMemo(() => {
    const counts = { all: files.length };
    for (const file of files) counts[file.docType] = (counts[file.docType] ?? 0) + 1;
    return counts;
  }, [files]);

  const visible = tab === "all" ? files : files.filter((f) => f.docType === tab);

  const summary = [
    `${files.length} ${files.length === 1 ? "file" : "files"}`,
    readyCount > 0 ? `${readyCount} uploaded` : null,
    uploadingCount > 0 ? `${uploadingCount} uploading` : null,
    blockedFiles.length > 0 ? `${blockedFiles.length} need attention` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const reviewDetected = () => {
    if (!canContinue) return;
    // Every uploaded file is carried forward with its type. The engine
    // runs the Drawings through the takeoff pipeline and reads the rest
    // (specs, addenda, scope) as context, so all of them inform the
    // estimate. Stash the real File objects for the processing screen.
    const ready = files
      .filter((f) => f.status === "ready")
      .map((f) => ({ file: f.file, docType: f.docType }));
    setUploadedFiles(projectId, ready);
    navigate(`/projects/${projectId}/documents/confirm`);
  };

  const openPicker = () => inputRef.current?.click();
  const compact = files.length > 0;

  const dropzone = (
    <div
      className={`dropzone${compact ? " dropzone--compact" : ""}${dragging ? " is-dragging" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <Upload aria-hidden="true" size={compact ? 18 : 28} />
      <p>{compact ? "Drag more PDF files here" : "Drag PDF files here"}</p>
      {compact ? null : (
        <p className="dropzone-hint">
          Drawings, specifications, addenda, and scope documents. Each file's type is detected from its name — change
          any that's wrong before starting.
        </p>
      )}
      <button type="button" className="btn" onClick={openPicker}>
        Choose files
      </button>
    </div>
  );

  // Rendered once, in a position that never changes, so the node behind
  // inputRef survives the dropzone moving.
  const fileInput = (
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
  );

  return (
    <>
      <AppTopBar
        title="Documents"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={
          <button type="button" className="btn btn--primary" disabled={!canContinue} onClick={reviewDetected}>
            Review detected drawings
          </button>
        }
      >
        <button type="button" className="btn" onClick={openPicker}>
          Upload files
        </button>
      </AppTopBar>

      {fileInput}

      <div className="workspace-body">
        <div className="page">
          {/* role="group" + aria-pressed, matching ProjectsFilters.jsx's
              chips. Not role="tab": these filter one table in place, and
              the tab pattern would promise a tabpanel relationship that
              does not exist here. */}
          <div className="filter-tabs" role="group" aria-label="Filter documents by type">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                aria-pressed={tab === key}
                className="filter-tab"
                onClick={() => setTab(key)}
              >
                {label}
                {countsByTab[key] ? <span className="filter-tab-count tabular">{countsByTab[key]}</span> : null}
              </button>
            ))}
            {files.length > 0 ? <p className="filter-tabs-summary tabular">{summary}</p> : null}
          </div>

          {/* The drop target leads the screen while the set is empty and
              steps back to a strip beneath the table once it isn't — the
              table is what an estimator has come to read by then. It is
              the same target either way: dropping, and the picker, behave
              identically in both states. */}
          {files.length === 0 ? dropzone : null}

          {files.length === 0 ? (
            <p className="muted">No files added yet.</p>
          ) : visible.length === 0 ? (
            <p className="muted">
              No {TABS.find((t) => t.key === tab)?.label.toLowerCase()} in this set. Every file is still counted below.
            </p>
          ) : (
            <div className="filecard">
              <table className="data-table upload-table filetable">
                <thead>
                  <tr>
                    <th scope="col">File</th>
                    <th scope="col">Type</th>
                    <th scope="col">State</th>
                    <th scope="col">
                      <span className="sr-only">Remove</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((file) => {
                    const state = STATE_COPY[file.status];
                    return (
                      <tr key={file.id}>
                        <th scope="row" className="upload-name">
                          <FileText aria-hidden="true" size={16} className="filetable-icon" />
                          <span>
                            <span className="filetable-filename">{file.name}</span>
                            <span className="filetable-meta tabular">{formatSize(file.size)}</span>
                          </span>
                        </th>
                        <td>
                          <label className="sr-only" htmlFor={`doctype-${file.id}`}>
                            Document type for {file.name}
                          </label>
                          <div className="doctype-cell">
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
                            {file.typeAuto ? <span className="doctype-detected">Detected</span> : null}
                          </div>
                        </td>
                        <td>
                          <span className={`upload-status upload-status--${state.tone}`}>{state.label}</span>
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
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {files.length > 0 ? dropzone : null}

          {readyCount > 0 && drawingsCount === 0 ? (
            <div className="warncard warncard--attention" role="status">
              <h4>
                <AlertTriangle aria-hidden="true" size={16} /> No drawing set yet
              </h4>
              <p>
                The takeoff runs on the drawings. Set at least one file's type to <strong>Drawings</strong> to continue —
                specifications and addenda are read as context, not as the drawing set.
              </p>
            </div>
          ) : null}
        </div>
      </div>

      {/* The footer states what is outstanding and carries the same two
          actions the screen has always ended with — it is where they are,
          not a second set. */}
      <footer className="workspace-footer">
        <div className="workspace-footer-status">
          {blockedFiles.length > 0 ? (
            <span className="footer-count footer-count--attention">
              <AlertCircle aria-hidden="true" size={14} />
              <span className="tabular">
                {blockedFiles.length} {blockedFiles.length === 1 ? "file needs" : "files need"} attention
              </span>
            </span>
          ) : null}
          {uploadingCount > 0 ? <span className="tabular">Uploading {uploadingCount}…</span> : null}
          {files.length > 0 && blockedFiles.length === 0 && uploadingCount === 0 ? (
            <span className="tabular">{summary}</span>
          ) : null}
        </div>
        <div className="workspace-footer-actions">
          <Link className="btn" to={`/projects/${projectId}`}>
            Save and exit
          </Link>
          <button type="button" className="btn btn--primary" disabled={!canContinue} onClick={reviewDetected}>
            Review detected drawings
          </button>
        </div>
      </footer>
    </>
  );
}
