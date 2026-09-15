/* ============================================================
   ConfirmDrawings.jsx — spec §5 screen D, "confirm detected
   information".

   Sits between upload and processing. It reflects the actual uploaded
   set, read from the API (store.listDocuments): the drawing files that
   will run through the takeoff, and the specifications/addenda that are
   read as context. What the estimator confirms before processing,
   surfaced in a Needs attention section ABOVE the table rather than
   buried in a row (spec §5): documents whose type wasn't recognized, and
   whether a drawing set is present at all. Types stay editable here,
   through store.setDocumentType.

   Sheet-level detail (revisions, per-sheet scale) is detected when the
   engine reads the drawings, so it belongs to processing, not this
   pre-processing confirmation. The checklist below says exactly that
   rather than showing a scale row it cannot yet fill: every line states
   something this screen actually knows, and the two that are genuinely
   deferred are marked as deferred instead of as passing.

   Adding a document you missed here goes back to screen C ("Add
   documents"), not a local picker on this screen -- an earlier version
   took files directly, but a file added that way was never uploaded to
   the API, so it silently vanished the moment "Start takeoff" stopped
   stashing anything for processing to read. Screen C is the one place a
   document actually reaches the API, and a type corrected on this screen
   is already persisted (store.setDocumentType), so nothing is lost by
   sending the estimator back to it.

   There is deliberately no "leave this one out" control in this slice --
   every listed document runs through the takeoff. The prior Include
   checkbox changed only local state; "Start takeoff" has never stashed
   an exclusion anywhere the API or the engine could see it, so the
   control described a decision that never actually reached processing.
   B4 (confirm-drawings write-back) is where exclusion comes back, as a
   real per-document decision persisted through the API rather than
   something a reload silently discards.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, Check, Clock, FileText } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { DOC_TYPES } from "../../lib/detectDocType.js";

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

export default function ConfirmDrawings({ store }) {
  const { projectId } = useParams();
  const navigate = useNavigate();

  const [rows, setRows] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState(false);

  // Sticks at false once the component unmounts, so a listDocuments
  // result that lands late is a no-op rather than a
  // set-state-after-unmount warning or a stale overwrite. Re-armed
  // inside the effect body itself, not only in its cleanup --
  // StrictMode's simulated mount/unmount/remount runs the cleanup once
  // in development, and a cleanup-only guard would stay false for the
  // rest of the component's life.
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const loadDocuments = () => {
    setLoadError(false);
    store
      .listDocuments(projectId)
      .then((docs) => {
        if (!aliveRef.current) return;
        setRows(docs.map((d) => ({ id: d.id, name: d.filename, size: d.sizeBytes, docType: d.docType })));
        setLoaded(true);
      })
      .catch(() => {
        if (!aliveRef.current) return;
        setLoadError(true);
        setLoaded(true);
      });
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, projectId]);

  const setType = (id, docType) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, docType } : r)));
    store.setDocumentType(id, docType).catch(() => {});
  };

  const counts = rows.reduce((acc, r) => ({ ...acc, [r.docType]: (acc[r.docType] || 0) + 1 }), {});
  const drawings = rows.filter((r) => r.docType === "Drawings");
  const unrecognized = rows.filter((r) => r.docType === "Other");
  const hasDrawings = drawings.length > 0;

  const start = () => {
    if (!hasDrawings) return;
    // Nothing to stash -- processing reads the same project's documents
    // straight from the API.
    navigate(`/projects/${projectId}/processing`);
  };

  const addDocumentsLink = (
    <Link className="btn" to={`/projects/${projectId}/documents`}>
      Add documents
    </Link>
  );

  if (!loaded) {
    return (
      <>
        <AppTopBar
          title="Confirm documents"
          breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        >
          {addDocumentsLink}
        </AppTopBar>
      </>
    );
  }

  if (rows.length === 0) {
    return (
      <>
        <AppTopBar
          title="Confirm documents"
          breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        >
          {addDocumentsLink}
        </AppTopBar>
        {loadError ? (
          <div className="workspace-body">
            <div className="page">
              <div className="warncard warncard--missing" role="alert">
                <h4>
                  <AlertTriangle aria-hidden="true" size={16} /> Couldn't load documents
                </h4>
                <p>Couldn't load this project's documents. Check the connection and try again.</p>
                <button type="button" className="btn" onClick={loadDocuments}>
                  Try again
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="empty-state">
            <h2>No documents to confirm</h2>
            <p>Add the drawing set and its documents first.</p>
            <Link className="btn btn--primary" to={`/projects/${projectId}/documents`}>
              Upload documents
            </Link>
          </div>
        )}
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
      ? { state: "ok", title: "Document types", detail: "Every document has a type" }
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
        {addDocumentsLink}
      </AppTopBar>

      <div className="workspace-body">
        <div className="page">
          <p className="muted page-intro">
            Drawings run through the takeoff; specifications and addenda are read as context. Correct any type before
            processing, or add a document you missed.
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

          <div className="filecard">
            <table className="data-table filetable">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Type</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
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
                        onChange={(e) => setType(r.id, e.target.value)}
                      >
                        {DOC_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
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
          <span className="tabular">{rows.length} {rows.length === 1 ? "document" : "documents"}</span>
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
