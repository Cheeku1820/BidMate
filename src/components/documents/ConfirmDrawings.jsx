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
   pre-processing confirmation. The checklist below says exactly that
   rather than showing a scale row it cannot yet fill: every line states
   something this screen actually knows, and the two that are genuinely
   deferred are marked as deferred instead of as passing.

   Adding files here. An estimator who realises a spec section is missing
   should not have to walk back to upload and lose the types they have
   already corrected, so this screen takes files too. It reuses upload's
   detection exactly -- the filename first, then, when the name wasn't
   informative, a look at the content through classifyDoc -- so a file
   added at either end of the flow gets typed the same way. Files that
   upload would have refused (a non-PDF, a copy already in the list) are
   refused here for the same reasons, named, and not silently added.
   ============================================================ */

import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, Check, Clock, FileText, Plus } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { getUploadedFiles, setUploadedFiles } from "../../lib/uploadedFiles.js";
import { DOC_TYPES, detectDocTypeInfo } from "../../lib/detectDocType.js";
import { classifyDoc } from "../../lib/engineClient.js";

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** One checklist line. `state` is "ok" | "blocking" | "attention" |
 *  "deferred", which are the product's own distinctions rather than new
 *  ones: "blocking" is the *Missing information* case (red, no override
 *  -- processing genuinely cannot run), "attention" is *Needs attention*
 *  (amber, an estimator's call). The icon and the words carry the state;
 *  the hue only reinforces (CLAUDE.md: never colour alone).
 *
 *  A passing row is not green. Green is reserved for estimator-approved
 *  content alone, and a derived pre-flight check is not that, however
 *  much a green tick would look like the layout this came from. */
const CHECKLIST_MARKS = {
  ok: { Icon: Check, word: "Confirmed" },
  blocking: { Icon: AlertCircle, word: "Blocks processing" },
  attention: { Icon: AlertTriangle, word: "Needs your attention" },
  deferred: { Icon: Clock, word: "Not known yet" },
};

function ChecklistRow({ state, title, detail }) {
  const { Icon, word: stateWord } = CHECKLIST_MARKS[state];
  return (
    <li className={`checklist-row checklist-row--${state}`}>
      <span className="checklist-mark" role="img" aria-label={stateWord} title={stateWord}>
        <Icon size={13} aria-hidden="true" />
      </span>
      <span className="checklist-text">
        <span className="checklist-title">{title}</span>
        <span className="checklist-detail">{detail}</span>
      </span>
    </li>
  );
}

export default function ConfirmDrawings() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);

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
  // Why a file the estimator just chose is not in the list. Cleared on
  // the next add, so it never lingers past the action it explains.
  const [rejected, setRejected] = useState([]);

  const setType = (id, docType) => setRows((prev) => prev.map((r) => (r.id === id ? { ...r, docType } : r)));
  const toggle = (id) => setRows((prev) => prev.map((r) => (r.id === id ? { ...r, included: !r.included } : r)));

  const addFiles = (fileList) => {
    const incoming = Array.from(fileList);
    const refusals = [];
    setRows((prev) => {
      let next = prev;
      for (const file of incoming) {
        const lower = file.name.toLowerCase();
        if (next.some((r) => r.name === file.name && r.size === file.size)) {
          refusals.push(`${file.name} is already in this list.`);
          continue;
        }
        if (!lower.endsWith(".pdf")) {
          refusals.push(`${file.name} isn't a PDF. Upload the document as a PDF.`);
          continue;
        }
        if (lower.includes("protected") || lower.includes("locked")) {
          refusals.push(`${file.name} is password protected. Upload an unlocked copy.`);
          continue;
        }
        const detected = detectDocTypeInfo(file.name);
        const id = `added-${file.name}-${file.size}-${crypto.randomUUID()}`;
        next = [...next, { id, name: file.name, size: file.size, docType: detected.type, file, included: true }];
        // Same two-step detection upload uses: the filename decides when
        // it is informative, and only when it isn't does the content get
        // read. Guarded on the row still existing and still holding the
        // guessed type, so a correction made while the look-up was in
        // flight is never overwritten.
        if (detected.source === "default") {
          classifyDoc(file).then((type) => {
            if (!type) return;
            setRows((cur) => cur.map((r) => (r.id === id && r.docType === detected.type ? { ...r, docType: type } : r)));
          });
        }
      }
      return next;
    });
    setRejected(refusals);
  };

  const kept = rows.filter((r) => r.included);
  const counts = kept.reduce((acc, r) => ({ ...acc, [r.docType]: (acc[r.docType] || 0) + 1 }), {});
  const drawings = kept.filter((r) => r.docType === "Drawings");
  const unrecognized = kept.filter((r) => r.docType === "Other");
  const excluded = rows.filter((r) => !r.included);
  const hasDrawings = drawings.length > 0;

  const start = () => {
    if (!hasDrawings) return;
    setUploadedFiles(
      projectId,
      kept.map((r) => ({ file: r.file, docType: r.docType })),
    );
    navigate(`/projects/${projectId}/processing`);
  };

  const openPicker = () => inputRef.current?.click();

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

  if (rows.length === 0) {
    return (
      <>
        <AppTopBar
          title="Confirm documents"
          breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        >
          <button type="button" className="btn" onClick={openPicker}>
            <Plus aria-hidden="true" size={15} /> Add files
          </button>
        </AppTopBar>
        {fileInput}
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

  // Every line states something this screen can actually check. The two
  // deferred lines are the engine's to answer, and say so.
  const checklist = [
    hasDrawings
      ? { state: "ok", title: "Drawing set", detail: `${drawings.length} ${drawings.length === 1 ? "document" : "documents"} run through the takeoff` }
      : { state: "blocking", title: "Drawing set", detail: "No document is typed Drawings — the takeoff has nothing to read" },
    unrecognized.length === 0
      ? { state: "ok", title: "Document types", detail: "Every included document has a type" }
      : {
          state: "attention",
          title: "Document types",
          detail: `${unrecognized.length} ${unrecognized.length === 1 ? "document is" : "documents are"} typed Other — confirm the type or leave as context`,
        },
    counts.Specifications
      ? { state: "ok", title: "Specifications", detail: `${counts.Specifications} read for schedules and requirements` }
      : { state: "attention", title: "Specifications", detail: "None included — schedules and material requirements won't be read" },
    {
      state: "ok",
      title: "Addenda",
      detail: counts.Addendum ? `${counts.Addendum} read for changes to the base set` : "None included",
    },
    {
      state: "ok",
      title: "Excluded documents",
      detail: excluded.length
        ? `${excluded.length} left out of processing`
        : "Nothing left out — every document is included",
    },
    {
      state: "deferred",
      title: "Legends and scales",
      detail: "Detected per sheet when the drawings are read, not before",
    },
  ];
  const blockingCount = checklist.filter((row) => row.state === "blocking").length;
  const attentionCount = checklist.filter((row) => row.state === "attention").length;
  const unresolvedCount = blockingCount + attentionCount;

  return (
    <>
      <AppTopBar
        title="Confirm documents"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={
          <button type="button" className="btn btn--primary" disabled={!hasDrawings} onClick={start}>
            Start takeoff
          </button>
        }
      >
        <button type="button" className="btn" onClick={openPicker}>
          <Plus aria-hidden="true" size={15} /> Add files
        </button>
      </AppTopBar>
      {fileInput}

      <div className="workspace-body">
        <div className="page">
          <p className="muted page-intro">
            Drawings run through the takeoff; specifications and addenda are read as context. Correct any type, add a
            document you missed, or leave one out, before processing.
          </p>

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

          {rejected.length > 0 ? (
            <div className="warncard warncard--attention" role="status">
              <h4>
                <AlertTriangle aria-hidden="true" size={16} />{" "}
                {rejected.length === 1 ? "1 file wasn't added" : `${rejected.length} files weren't added`}
              </h4>
              <ul className="warncard-list">
                {rejected.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="filecard">
            <table className="data-table filetable">
              <thead>
                <tr>
                  <th scope="col">
                    <span className="sr-only">Include</span>
                  </th>
                  <th scope="col">Document</th>
                  <th scope="col">Type</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className={r.included ? undefined : "is-excluded"}>
                    <td>
                      <input type="checkbox" aria-label={`Include ${r.name}`} checked={r.included} onChange={() => toggle(r.id)} />
                    </td>
                    <th scope="row" className="upload-name">
                      <FileText aria-hidden="true" size={16} className="filetable-icon" />
                      <span>
                        <span className="filetable-filename">{r.name}</span>
                        <span className="filetable-meta tabular">{formatSize(r.size)}</span>
                      </span>
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
                    <td>
                      <span className={r.included ? "upload-status upload-status--ready" : "upload-status"}>
                        {r.included ? "Included" : "Left out"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <section className="checklist-card">
            <header className="checklist-head">
              <h2>Confirm before takeoff processing</h2>
              <p
                className={
                  unresolvedCount > 0 ? "checklist-count checklist-count--attention tabular" : "checklist-count tabular"
                }
              >
                {unresolvedCount > 0
                  ? `${unresolvedCount} of ${checklist.length} need your attention`
                  : `${checklist.length} of ${checklist.length} confirmed`}
              </p>
            </header>
            <ul className="checklist">
              {checklist.map((row) => (
                <ChecklistRow key={row.title} {...row} />
              ))}
            </ul>
          </section>
        </div>
      </div>

      <footer className="workspace-footer">
        <div className="workspace-footer-status">
          {blockingCount > 0 ? (
            <span className="footer-count footer-count--missing">
              <AlertCircle aria-hidden="true" size={14} />
              <span className="tabular">{blockingCount} blocking</span>
            </span>
          ) : null}
          {attentionCount > 0 ? (
            <span className="footer-count footer-count--attention">
              <AlertTriangle aria-hidden="true" size={14} />
              <span className="tabular">{attentionCount} need attention</span>
            </span>
          ) : null}
          <span className="tabular">
            {kept.length} of {rows.length} documents included
          </span>
        </div>
        <div className="workspace-footer-actions">
          <Link className="btn" to={`/projects/${projectId}/documents`}>
            Back to documents
          </Link>
          <button type="button" className="btn btn--primary" disabled={!hasDrawings} onClick={start}>
            Start takeoff
          </button>
        </div>
      </footer>
    </>
  );
}
