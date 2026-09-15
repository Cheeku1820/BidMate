/* ============================================================
   UploadDocuments.jsx — spec §5 screen C, the intake path, as a view
   onto the API (Task 6).

   Documents live server-side now: the list is fetched from
   store.listDocuments on mount, a drop uploads through
   store.uploadDocument with real progress, a type change and a remove
   go through store.setDocumentType / store.deleteDocument. Nothing is
   stashed locally for the next screen -- ConfirmDrawings reads the same
   project's documents from the API itself.

   `rows` holds both persisted documents (state "ready", from the API,
   carrying the server's id) and in-flight local rows (uploading, or one
   that never reached the server: duplicate / unsupported / failed) in
   one list, so the table and every derived count read one source. The
   full set of intake states spec §10 requires stays intact -- uploading,
   uploaded, duplicate, unsupported, failed -- each stated in plain
   language, never a bare "something went wrong". A duplicate or
   unsupported classification is now the server's decision, not a guess
   made from the filename; only the "is this even a PDF" check stays
   client-side, because that one never needs a round trip to answer.

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

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, FileText, Upload, X } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Modal from "../Modal.jsx";
import { DOC_TYPES, detectDocTypeInfo } from "../../lib/detectDocType.js";
import { classifyDoc } from "../../lib/engineClient.js";

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

// Row state drives the words in the state column directly (the words are
// the state -- CLAUDE.md: status is never colour alone). `STATE_TONE` maps
// each state onto the existing red/blue CSS hues in styles.css so a new
// failure kind doesn't need a new stylesheet rule: duplicate, unsupported,
// and failed all read as "needs attention" red, same as before.
const STATE_TONE = {
  uploading: "uploading",
  ready: "ready",
  duplicate: "unsupported",
  unsupported: "unsupported",
  failed: "unsupported",
};

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadDocuments({ store }) {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [rows, setRows] = useState([]); // persisted docs + in-flight uploads, one list
  const [confirming, setConfirming] = useState(null); // a row awaiting delete confirmation
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState("all");

  useEffect(() => {
    let live = true;
    store.listDocuments(projectId).then((docs) => {
      if (!live) return;
      // Merge rather than replace: this fetch can resolve after the
      // estimator has already dropped a file, and a local row that
      // hasn't reached the server yet (uploading, or one that never
      // will -- duplicate, unsupported, failed) must survive the mount
      // list landing, not be clobbered by it.
      const seeded = docs.map((d) => ({ ...d, state: "ready", progress: 100, key: d.id }));
      setRows((prev) => [...seeded, ...prev.filter((r) => !seeded.some((s) => s.key === r.key))]);
    });
    return () => {
      live = false;
    };
  }, [store, projectId]);

  const update = (key, patch) =>
    setRows((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const addFiles = (fileList) => {
    for (const file of Array.from(fileList)) {
      const key = `${file.name}-${file.size}-${crypto.randomUUID()}`;
      const isPdf = file.name.toLowerCase().endsWith(".pdf") && file.type === "application/pdf";

      if (!isPdf) {
        setRows((prev) => [
          ...prev,
          {
            key,
            filename: file.name,
            sizeBytes: file.size,
            docType: "Other",
            state: "unsupported",
            message: `${file.name} isn't a PDF. Upload PDF drawings, specifications, addenda, and scope documents.`,
          },
        ]);
        continue;
      }

      const detected = detectDocTypeInfo(file.name);
      const docType = detected.type;
      setRows((prev) => [
        ...prev,
        {
          key,
          filename: file.name,
          sizeBytes: file.size,
          docType,
          typeAuto: true,
          state: "uploading",
          progress: 0,
        },
      ]);

      store
        .uploadDocument(projectId, file, docType, { onProgress: (p) => update(key, { progress: p }) })
        .then((doc) => {
          setRows((prev) => prev.map((r) => (r.key === key ? { ...doc, state: "ready", progress: 100, key: doc.id } : r)));
          // A filename that wasn't informative gets a content-based
          // second look, applied to the persisted row -- but only if the
          // estimator hasn't since set the type by hand.
          if (detected.source === "default") {
            classifyDoc(file).then((type) => {
              if (!type) return;
              // The state updater must stay pure -- StrictMode invokes it
              // twice in development -- so the decision of whether to
              // write through is captured here and the API call happens
              // once, after the dispatch, rather than inside it.
              let stillAuto = false;
              setRows((prev) => {
                const row = prev.find((r) => r.key === doc.id);
                if (!row || !row.typeAuto) return prev;
                stillAuto = true;
                return prev.map((r) => (r.key === doc.id ? { ...r, docType: type } : r));
              });
              if (stillAuto) store.setDocumentType(doc.id, type);
            });
          }
        })
        .catch((err) => {
          const state = err.code === "duplicate_document" ? "duplicate" : err.code === "unsupported_document" ? "unsupported" : "failed";
          update(key, { state, message: err.message });
        });
    }
  };

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
  };

  // A row that never reached the server has nothing to confirm with --
  // it's removed locally, no dialog. A persisted row asks first.
  const requestRemove = (row) => {
    if (row.state === "ready") setConfirming(row);
    else setRows((prev) => prev.filter((r) => r.key !== row.key));
  };

  const confirmRemove = async () => {
    const row = confirming;
    setConfirming(null);
    await store.deleteDocument(row.id);
    setRows((prev) => prev.filter((r) => r.key !== row.key));
  };

  // A manual change turns off the "detected" hint -- the estimator owns
  // the value now. A persisted row writes through the API; a row still
  // uploading just changes the type it will finish uploading with.
  const setDocType = (row, docType) => {
    update(row.key, { docType, typeAuto: false });
    if (row.state === "ready") store.setDocumentType(row.id, docType);
  };

  // Derived from `rows`, never from the filtered view. See the header.
  const readyCount = rows.filter((r) => r.state === "ready").length;
  const uploadingCount = rows.filter((r) => r.state === "uploading").length;
  const blockedRows = rows.filter((r) => ["duplicate", "unsupported", "failed"].includes(r.state));
  const drawingsCount = rows.filter((r) => r.state === "ready" && r.docType === "Drawings").length;
  // The takeoff runs on the drawing set, so at least one file has to be
  // typed Drawings before there's anything to process.
  const canContinue = drawingsCount > 0;

  const countsByTab = useMemo(() => {
    const counts = { all: rows.length };
    for (const row of rows) counts[row.docType] = (counts[row.docType] ?? 0) + 1;
    return counts;
  }, [rows]);

  const visible = tab === "all" ? rows : rows.filter((r) => r.docType === tab);

  const summary = [
    `${rows.length} ${rows.length === 1 ? "file" : "files"}`,
    readyCount > 0 ? `${readyCount} uploaded` : null,
    uploadingCount > 0 ? `${uploadingCount} uploading` : null,
    blockedRows.length > 0 ? `${blockedRows.length} need attention` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const reviewDetected = () => {
    if (!canContinue) return;
    // Nothing to stash -- the confirm screen reads this project's
    // documents from the API itself.
    navigate(`/projects/${projectId}/documents/confirm`);
  };

  const openPicker = () => inputRef.current?.click();
  const compact = rows.length > 0;

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
      {/* The primary action lives once, in the footer -- unlike
          ConfirmDrawings' matching top-bar-plus-footer pair, this screen
          keeps a single "Review detected drawings" control so its
          accessible name stays unambiguous for anyone navigating by
          role and name, keyboard or screen reader alike. */}
      <AppTopBar title="Documents" breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}>
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
            {rows.length > 0 ? <p className="filter-tabs-summary tabular">{summary}</p> : null}
          </div>

          {/* The drop target leads the screen while the set is empty and
              steps back to a strip beneath the table once it isn't — the
              table is what an estimator has come to read by then. It is
              the same target either way: dropping, and the picker, behave
              identically in both states. */}
          {rows.length === 0 ? dropzone : null}

          {rows.length === 0 ? (
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
                  {visible.map((row) => (
                    <tr key={row.key}>
                      <th scope="row" className="upload-name">
                        <FileText aria-hidden="true" size={16} className="filetable-icon" />
                        <span>
                          <span className="filetable-filename">{row.filename}</span>
                          <span className="filetable-meta tabular">{formatSize(row.sizeBytes)}</span>
                        </span>
                      </th>
                      <td>
                        <div className="doctype-cell">
                          <select
                            aria-label={`Type for ${row.filename}`}
                            className="field field--compact"
                            value={row.docType}
                            onChange={(event) => setDocType(row, event.target.value)}
                          >
                            {DOC_TYPES.map((type) => (
                              <option key={type} value={type}>
                                {type}
                              </option>
                            ))}
                          </select>
                          {row.typeAuto ? <span className="doctype-detected">Detected</span> : null}
                        </div>
                      </td>
                      <td>
                        <span className={`upload-status upload-status--${STATE_TONE[row.state]}`}>
                          {row.state === "uploading"
                            ? `Uploading… ${row.progress}%`
                            : row.state === "ready"
                              ? "Uploaded"
                              : row.message}
                        </span>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="iconbtn"
                          aria-label={`Remove ${row.filename}`}
                          onClick={() => requestRemove(row)}
                        >
                          <X aria-hidden="true" size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {rows.length > 0 ? dropzone : null}

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

      {confirming ? (
        <Modal
          title={`Remove ${confirming.filename}?`}
          onClose={() => setConfirming(null)}
          foot={
            <>
              <button type="button" className="btn" onClick={() => setConfirming(null)}>
                Cancel
              </button>
              <button type="button" className="btn btn--primary" onClick={confirmRemove}>
                Remove
              </button>
            </>
          }
        >
          <p>It will be removed from this project. Upload it again if you need it back.</p>
        </Modal>
      ) : null}

      {/* The footer states what is outstanding and carries the same two
          actions the screen has always ended with — it is where they are,
          not a second set. */}
      <footer className="workspace-footer">
        <div className="workspace-footer-status">
          {blockedRows.length > 0 ? (
            <span className="footer-count footer-count--attention">
              <AlertCircle aria-hidden="true" size={14} />
              <span className="tabular">
                {blockedRows.length} {blockedRows.length === 1 ? "file needs" : "files need"} attention
              </span>
            </span>
          ) : null}
          {/* Lowercase, matching the tab summary's "N uploading" phrasing
              above -- distinct wording from a row's own "Uploading… N%"
              state text, so the two never read as the same string. */}
          {uploadingCount > 0 ? <span className="tabular">{uploadingCount} uploading…</span> : null}
          {rows.length > 0 && blockedRows.length === 0 && uploadingCount === 0 ? (
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
