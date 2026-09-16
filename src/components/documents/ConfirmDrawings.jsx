/* ============================================================
   ConfirmDrawings.jsx — spec §5 screen D, "confirm detected
   information".

   Sits between upload and processing. It reflects the set as the worker
   has read it (store.getProcessing): every uploaded document with what
   was made of it -- read, with the number of sheets found; still
   reading; or failed, with the reason -- and the scope statements the
   worker lifted out of the documents, for the estimator to settle
   before the takeoff runs (ScopeSection.jsx, above the table). What the
   estimator confirms here is surfaced in a Needs attention section
   ABOVE the table rather than buried in a row (spec §5): documents
   whose type wasn't recognized, and whether a drawing set is present at
   all. Types stay editable here, through store.setDocumentType.

   While any document is still being read this screen polls
   store.getProcessing every few seconds, the same way screen C does, so
   a set that finishes reading while the estimator is looking at it
   shows its sheet counts without a reload.

   Under each drawing set the worker has read, the sheets it found are
   listed -- number, title, kind, and, for a sheet the worker could not
   read, the reason -- so the estimator sees what the takeoff will
   count before starting it (spec §8). An unreadable sheet is marked
   with an icon and words, never a colour alone, and never with the
   four review labels: a sheet's readability is not an item's evidence.

   "Start takeoff" asks the server to start a run (store.startTakeoff)
   and then goes to processing. It is disabled while any document is
   still being read -- a set the worker has not finished with would be
   left out of the run silently, and the server refuses the same case
   (`drawings_still_reading`), shown inline if it ever lands. A run
   already in flight is treated as already started -- the estimator
   lands on the same processing screen either way. A set with nothing
   readable is a message to show here, inline, next to the documents
   that need replacing; not a page to leave.

   Sheet-level detail (revisions, per-sheet scale) is detected when the
   engine reads the drawings, so it belongs to processing, not this
   pre-processing confirmation. The checklist below says exactly that
   rather than showing a scale row it cannot yet fill: every line states
   something this screen actually knows, and the one that is genuinely
   deferred is marked as deferred instead of as passing.

   Adding a document you missed here goes back to screen C ("Add
   documents"), not a local picker on this screen -- screen C is the one
   place a document actually reaches the API, and a type corrected on
   this screen is already persisted (store.setDocumentType), so nothing
   is lost by sending the estimator back to it.

   There is deliberately no "leave this one out" control in this slice --
   every listed document runs through the takeoff. The prior Include
   checkbox changed only local state and never reached processing. B4
   (confirm-drawings write-back) is where exclusion comes back, as a
   real per-document decision persisted through the API.
   ============================================================ */

import { Fragment, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertCircle, AlertTriangle, Check, CheckCircle2, Clock, FileText, Loader2 } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ScopeSection from "./ScopeSection.jsx";
import { DOC_TYPES } from "../../lib/detectDocType.js";

// How often to ask again while a document is still being read. Matches
// screen C's poll; nothing here needs to be faster than the worker.
const READ_POLL_MS = 3000;

// What the row says when the server marks a document failed but gives
// no reason -- the server's own words are preferred; this is only the
// floor under an empty one.
const FAILED_FALLBACK = "This file couldn't be read. Upload it again, or replace it.";

// Why Start is disabled while a document is still being read. The same
// sentence the server answers with (copy.DRAWINGS_READING) when a start
// reaches it in that state, so the two never disagree.
const READING_HELP = "A drawing set is still being read. Wait for it to finish before starting the takeoff.";

// A spec or an addendum can genuinely carry no drawing sheets -- that's
// not a failure, so 0 reads as plain "Read" rather than "Read · 0
// sheets". Same wording as screen C.
function readLabel(sheetCount) {
  if (!sheetCount) return "Read";
  return `Read · ${sheetCount} ${sheetCount === 1 ? "sheet" : "sheets"}`;
}

/** What the worker made of one document: icon + words, in the tone
 *  screen C uses for the same states. Read is blue -- done, not judged,
 *  never green (CLAUDE.md). Failed is red with the reason on the row. */
function ReadState({ row }) {
  if (row.state === "failed") {
    return <span className="upload-status upload-status--unsupported">{row.reason || FAILED_FALLBACK}</span>;
  }
  if (row.state === "read") {
    return (
      <span className="upload-status upload-status--read">
        <CheckCircle2 aria-hidden="true" size={14} className="ink-blue" /> {readLabel(row.sheetCount)}
      </span>
    );
  }
  return (
    <span className="upload-status upload-status--reading">
      <Loader2 aria-hidden="true" size={14} className="spin" /> Reading…
    </span>
  );
}

/** The sheets the worker found in one read drawing set, as a compact
 *  table under the document's row. An unreadable sheet says so with an
 *  icon and the worker's own reason -- hue reinforces, never carries
 *  (CLAUDE.md). No review-label pill: readability describes a sheet,
 *  not an item's evidence, and dressing it as one would make the four
 *  labels five. */
function SheetList({ row }) {
  return (
    <table className="sheetlist" aria-label={`Sheets in ${row.name}`}>
      <thead>
        <tr>
          <th scope="col">Sheet</th>
          <th scope="col">Title</th>
          <th scope="col">Kind</th>
        </tr>
      </thead>
      <tbody>
        {row.sheets.map((sheet) => (
          <tr key={sheet.id} className={sheet.unreadableReason ? "sheetlist-row--unreadable" : undefined}>
            <th scope="row" className="tabular">
              {sheet.number}
            </th>
            <td>
              {sheet.title}
              {sheet.unreadableReason ? (
                <span className="sheetlist-unreadable">
                  <AlertTriangle aria-hidden="true" size={13} /> Unreadable — {sheet.unreadableReason}
                </span>
              ) : null}
            </td>
            <td>{sheet.kind}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
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
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");

  // Sticks at false once the component unmounts, so a getProcessing
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

  // A row is the processing response's view of a document: what the
  // worker made of it. A type the estimator has just changed locally is
  // kept over the server's copy until the retype lands (the poll below
  // would otherwise flash the old type back for a beat), and a retype
  // failure's message survives a poll for the same reason.
  const toRow = (d, prev) => ({
    id: d.id,
    name: d.filename,
    docType: prev?.pendingType ?? d.docType,
    pendingType: prev?.pendingType,
    error: prev?.error,
    state: d.state,
    reason: d.reason,
    sheetCount: d.sheetCount,
    sheets: d.sheets ?? [],
  });

  const loadDocuments = () => {
    setLoadError(false);
    store
      .getProcessing(projectId)
      .then(({ documents }) => {
        if (!aliveRef.current) return;
        setRows((prev) => documents.map((d) => toRow(d, prev.find((r) => r.id === d.id))));
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

  // While any document is still being read, ask again every few seconds
  // -- and stop the moment nothing is. Keyed on the boolean so the
  // interval restarts only when reading starts or stops, not on every
  // unrelated row change. A poll that fails is left alone: the rows
  // keep their last known state and the next tick tries again.
  const anyReading = rows.some((r) => r.state === "reading");
  useEffect(() => {
    if (!anyReading) return undefined;
    const tick = () => {
      store
        .getProcessing(projectId)
        .then(({ documents }) => {
          if (!aliveRef.current) return;
          setRows((prev) => documents.map((d) => toRow(d, prev.find((r) => r.id === d.id))));
        })
        .catch(() => {});
    };
    const interval = setInterval(tick, READ_POLL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyReading, store, projectId]);

  // The select follows the server. It shows the new type at once, but a
  // write the server refuses reverts it and puts the server's own words
  // on the row -- otherwise the select shows a type the server never
  // accepted, "Start takeoff" enables on a drawing set that does not
  // exist server-side, and processing reads the old type. The row stays
  // in every count either way: the document is still there, and can be
  // retyped again. Same behaviour as UploadDocuments.setDocType.
  const setType = (id, docType) => {
    const previous = rows.find((r) => r.id === id)?.docType;
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, docType, pendingType: docType, error: undefined } : r)));
    store
      .setDocumentType(id, docType)
      .then(() => {
        if (!aliveRef.current) return;
        setRows((prev) => prev.map((r) => (r.id === id ? { ...r, docType, pendingType: undefined, error: undefined } : r)));
      })
      .catch((err) => {
        if (!aliveRef.current) return;
        setRows((prev) =>
          prev.map((r) => (r.id === id ? { ...r, docType: previous, pendingType: undefined, error: err.message } : r))
        );
      });
  };

  const counts = rows.reduce((acc, r) => ({ ...acc, [r.docType]: (acc[r.docType] || 0) + 1 }), {});
  const drawings = rows.filter((r) => r.docType === "Drawings");
  const unrecognized = rows.filter((r) => r.docType === "Other");
  const hasDrawings = drawings.length > 0;

  const sheetsRead = rows.reduce((n, r) => n + (r.sheetCount || 0), 0);
  // Start waits for every read to land. A document the worker has not
  // finished with would be left out of the run, and its sheets would
  // then sit at "Waiting" under a run that has finished.
  const canStart = hasDrawings && !anyReading && !starting;

  // The server decides whether a run can start. A run already in flight
  // is the outcome the estimator wanted -- processing is where they were
  // headed -- so it is not an error here. Anything else stays on this
  // screen with the server's own words next to the documents.
  const start = () => {
    if (!canStart) return;
    setStarting(true);
    setStartError("");
    store
      .startTakeoff(projectId)
      .then(() => {
        if (!aliveRef.current) return;
        navigate(`/projects/${projectId}/processing`);
      })
      .catch((err) => {
        if (!aliveRef.current) return;
        if (err?.code === "run_in_flight") {
          navigate(`/projects/${projectId}/processing`);
          return;
        }
        setStarting(false);
        setStartError(err?.message || "Couldn't start the takeoff. Check the connection and try again.");
      });
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
      ? {
          state: "ok",
          title: "Drawing set",
          detail: `${drawings.length} ${drawings.length === 1 ? "document" : "documents"} run through the takeoff${
            sheetsRead ? ` · ${sheetsRead} ${sheetsRead === 1 ? "sheet" : "sheets"} read` : ""
          }`,
        }
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
  // A deferred line is neither confirmed nor unresolved -- it is a
  // question this screen cannot answer yet, and it says so. The tally
  // counts only the lines that can be confirmed here, so "4 of 4
  // confirmed" is true rather than "5 of 5" with one of the five
  // reading "Not known yet".
  const confirmableCount = checklist.filter((row) => row.state !== "deferred").length;
  const confirmedCount = checklist.filter((row) => row.state === "ok").length;

  return (
    <>
      <AppTopBar
        title="Confirm documents"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={
          <button
            type="button"
            className="btn btn--primary"
            disabled={!canStart}
            aria-describedby={anyReading ? "start-takeoff-help" : undefined}
            onClick={start}
          >
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

          {startError ? (
            <div className="warncard warncard--missing" role="alert">
              <h4>
                <AlertTriangle aria-hidden="true" size={16} /> Couldn't start the takeoff
              </h4>
              <p>{startError}</p>
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

          <ScopeSection store={store} projectId={projectId} />

          <div className="filecard">
            <table className="data-table filetable">
              <thead>
                <tr>
                  <th scope="col">Document</th>
                  <th scope="col">Type</th>
                  <th scope="col">State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <Fragment key={r.id}>
                    <tr>
                      <th scope="row" className="upload-name">
                        <FileText aria-hidden="true" size={16} className="filetable-icon" />
                        <span className="filetable-filename">{r.name}</span>
                      </th>
                      <td>
                        <label className="sr-only" htmlFor={`confirm-type-${r.id}`}>
                          Type for {r.name}
                        </label>
                        <select
                          id={`confirm-type-${r.id}`}
                          className="field field--compact"
                          value={r.docType}
                          aria-describedby={r.error ? `confirm-type-error-${r.id}` : undefined}
                          onChange={(e) => setType(r.id, e.target.value)}
                        >
                          {DOC_TYPES.map((type) => (
                            <option key={type} value={type}>
                              {type}
                            </option>
                          ))}
                        </select>
                        {/* Always rendered so the live region exists before
                            it has anything to say -- a region created at
                            the same moment as its content is not reliably
                            announced. Adjacent to the field it describes
                            (spec §8), in the failed tone the upload table
                            uses for the same kind of failure. */}
                        <p
                          id={`confirm-type-error-${r.id}`}
                          className="upload-status upload-status--unsupported doctype-error"
                          aria-live="polite"
                        >
                          {r.error || null}
                        </p>
                      </td>
                      {/* A live region per row, so a document that finishes
                          reading after the estimator has moved on is
                          announced rather than changing silently. */}
                      <td aria-live="polite" aria-atomic="true">
                        <ReadState row={r} />
                      </td>
                    </tr>
                    {r.docType === "Drawings" && r.state === "read" && r.sheets.length > 0 ? (
                      <tr className="sheetlist-holder">
                        <td colSpan={3}>
                          <SheetList row={r} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
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
                  ? `${unresolvedCount} of ${confirmableCount} need your attention`
                  : `${confirmedCount} of ${confirmableCount} confirmed`}
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
          <div className="footer-primary">
            <button
              type="button"
              className="btn btn--primary"
              disabled={!canStart}
              aria-describedby={anyReading ? "start-takeoff-help" : undefined}
              onClick={start}
            >
              Start takeoff
            </button>
            {/* Always in the tree so the id resolves the moment a read
                starts; empty when nothing is reading. */}
            <p id="start-takeoff-help" className="footer-help">
              {anyReading ? READING_HELP : null}
            </p>
          </div>
        </div>
      </footer>
    </>
  );
}
