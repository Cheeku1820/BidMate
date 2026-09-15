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

// What the row says when the server marks a document failed but gives
// no reason. The server's own `error` text is preferred whenever it is
// there; this is only the floor under an empty one, because a failed
// document with no words next to it is exactly the silence that reads
// as completeness.
const FAILED_FALLBACK = "This file couldn't be read. Upload it again, or replace it.";

/** A persisted document, as the API returns it, turned into a row.
 *
 *  The row's state comes from the server's `status`, never assumed.
 *  `uploaded` is the only status this slice writes, and it is the row's
 *  "ready" state. Anything else is not "Uploaded" and must not render
 *  as if it were: the worker that lands later (B2) reports back through
 *  this same field, and the day it writes `failed`, that document has
 *  to show the failure and its `error` text in the failed tone -- not
 *  sit in the list looking done. Until the worker's intermediate
 *  statuses exist to be rendered, every non-`uploaded` status takes the
 *  failed tone rather than the "done" one; the honest default is the
 *  one that does not overstate.
 *
 *  `error` is left off the row deliberately: on a row it means a failed
 *  retype or remove on an otherwise-ready document (see setDocType and
 *  confirmRemove), and the server's `error` is a different thing --
 *  it is why the document itself failed, and it goes in `message`, the
 *  same field a duplicate or unsupported upload's copy lives in. */
function rowFromDocument(d) {
  if (d.status === "uploaded") {
    return { ...d, error: undefined, state: "ready", progress: 100 };
  }
  return { ...d, error: undefined, state: "failed", progress: 100, message: d.error || FAILED_FALLBACK };
}

export default function UploadDocuments({ store }) {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [rows, setRows] = useState([]); // persisted docs + in-flight uploads, one list
  const [confirming, setConfirming] = useState(null); // a row awaiting delete confirmation
  const [dragging, setDragging] = useState(false);
  const [tab, setTab] = useState("all");
  const [loadError, setLoadError] = useState(false);

  // `rowsRef` mirrors `rows` synchronously. A couple of call sites need
  // to read the *current* row set to decide whether a side effect
  // (writing a type back through the API) should fire, and a functional
  // setRows updater isn't a safe place to do that read -- it has to stay
  // pure (React can invoke it more than once, and defers it under
  // concurrent updates), so the decision can't live inside one. Every
  // update to `rows` goes through `setRowsSafe` below, which keeps this
  // ref and the state in lockstep.
  const rowsRef = useRef([]);
  const setRowsSafe = (updater) => {
    const next = typeof updater === "function" ? updater(rowsRef.current) : updater;
    rowsRef.current = next;
    setRows(next);
  };

  // In-flight upload promises, by row key, so a remove can cancel the
  // actual request -- not just stop watching it. Without this, removing
  // a row mid-upload only forgets it locally; the XHR keeps going, the
  // server persists the document, and it reappears "Uploaded" on the
  // next reload with no way the estimator asked for it to stay.
  const inFlightRef = useRef(new Map());

  // Sticks at false once the component unmounts, so a `listDocuments`
  // resolving (or rejecting) after that point is a no-op rather than a
  // set-state-after-unmount warning or a stale overwrite.
  const aliveRef = useRef(true);
  useEffect(() => {
    // The effect body has to re-arm the ref, not just declare a cleanup
    // -- StrictMode's simulated mount/unmount/remount runs the cleanup
    // once in development, and with only a cleanup here the ref would
    // stay false for the component's whole remaining life, discarding
    // every future listDocuments result behind the `!aliveRef.current`
    // guards below.
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
        // Merge rather than replace: this fetch can resolve after the
        // estimator has already dropped a file, and a local row that
        // hasn't reached the server yet (uploading, or one that never
        // will -- duplicate, unsupported, failed) must survive the mount
        // list landing, not be clobbered by it.
        const seeded = docs.map((d) => ({ ...rowFromDocument(d), key: d.id }));
        setRowsSafe((prev) => [...seeded, ...prev.filter((r) => !seeded.some((s) => s.key === r.key))]);
      })
      .catch(() => {
        if (!aliveRef.current) return;
        // Silence here would read as "no documents yet" -- an empty
        // project and a project this screen couldn't reach must never
        // look the same.
        setLoadError(true);
      });
  };

  useEffect(() => {
    loadDocuments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, projectId]);

  const update = (key, patch) =>
    setRowsSafe((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const addFiles = (fileList) => {
    for (const file of Array.from(fileList)) {
      const key = `${file.name}-${file.size}-${crypto.randomUUID()}`;
      const isPdf = file.name.toLowerCase().endsWith(".pdf") && file.type === "application/pdf";

      if (!isPdf) {
        setRowsSafe((prev) => [
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
      setRowsSafe((prev) => [
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

      const uploadPromise = store.uploadDocument(projectId, file, docType, {
        onProgress: (p) => update(key, { progress: p }),
      });
      // Kept so a remove mid-upload can cancel the actual request. See
      // requestRemove.
      inFlightRef.current.set(key, uploadPromise);

      uploadPromise
        .then((doc) => {
          inFlightRef.current.delete(key);
          // Read the live local row *before* it's overwritten below --
          // the estimator may have retyped this row while it was still
          // uploading. The form data already carried the type it was
          // uploaded with, so that local change hasn't reached the
          // server yet and the merge below would otherwise lose it
          // silently.
          const localRow = rowsRef.current.find((r) => r.key === key);
          const localDocType = localRow?.docType;
          const localTypeAuto = localRow?.typeAuto ?? true;
          // `typeAuto` is the row's own knowledge, not the server's --
          // it has to be carried across the overwrite. Dropping it here
          // did two things at once: the "Detected" hint vanished the
          // moment an upload settled, and the content-based second look
          // below, which checks `row.typeAuto` before writing, found
          // it undefined and never wrote anything.
          setRowsSafe((prev) => prev.map((r) => (r.key === key ? { ...rowFromDocument(doc), key: doc.id, typeAuto: localTypeAuto } : r)));

          if (!localTypeAuto && localDocType && localDocType !== doc.docType) {
            // Forward the retype that happened mid-upload, now that
            // there's a document id to PATCH.
            store
              .setDocumentType(doc.id, localDocType)
              .then((updated) => {
                setRowsSafe((prev) => prev.map((r) => (r.key === doc.id ? { ...r, docType: updated.docType, error: undefined } : r)));
              })
              .catch((err) => update(doc.id, { error: err.message }));
          } else if (localTypeAuto && detected.source === "default") {
            // A filename that wasn't informative gets a content-based
            // second look, applied to the persisted row -- but only if
            // the estimator hasn't since set the type by hand.
            classifyDoc(file)
              .then((type) => {
                if (!type) return;
                // Read the live mirror synchronously rather than deciding
                // inside a setRows updater -- an updater has to stay pure
                // and isn't guaranteed to run eagerly, so it's not a safe
                // place to gate a side effect. rowsRef is always current
                // because every row update goes through setRowsSafe.
                const row = rowsRef.current.find((r) => r.key === doc.id);
                if (!row || !row.typeAuto) return;
                // The persisted row is the truth; the select follows the
                // server's answer rather than the guess. A write that
                // fails leaves the row on the type it was uploaded with
                // -- still "Detected", still counted -- and says so in
                // the state column, the same way a manual retype that
                // fails does.
                store
                  .setDocumentType(doc.id, type)
                  .then((updated) => {
                    setRowsSafe((prev) => prev.map((r) => (r.key === doc.id ? { ...r, docType: updated.docType, error: undefined } : r)));
                  })
                  .catch((err) => update(doc.id, { error: err.message }));
              })
              // The engine being unreachable is the common case, not an
              // edge one -- it runs on the estimator's own machine. The
              // second look is a refinement of a guess that already
              // stands; without it the row simply keeps the type its
              // filename suggested, which is what it showed all along.
              .catch(() => {});
          }
        })
        .catch((err) => {
          inFlightRef.current.delete(key);
          // A cancelled upload already has its row removed locally
          // (requestRemove did that synchronously) -- there is nothing
          // left to surface the failure on.
          if (err.code === "aborted") return;
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

  // A row with no server id has nothing to confirm with -- it never
  // reached the server (duplicate / unsupported / failed), or it's still
  // in flight, in which case removing it aborts the upload outright
  // rather than just forgetting about it locally while the request (and
  // whatever the server does with it) keeps going. A persisted row --
  // any row that does have an id, including one a retype or a delete
  // attempt later failed on -- asks first.
  const requestRemove = (row) => {
    if (row.id) {
      setConfirming(row);
      return;
    }
    if (row.state === "uploading") {
      inFlightRef.current.get(row.key)?.abort?.();
      inFlightRef.current.delete(row.key);
    }
    setRowsSafe((prev) => prev.filter((r) => r.key !== row.key));
  };

  const confirmRemove = async () => {
    const row = confirming;
    setConfirming(null);
    try {
      await store.deleteDocument(row.id);
      setRowsSafe((prev) => prev.filter((r) => r.key !== row.key));
    } catch (err) {
      // The row stays -- silently doing nothing would look like the
      // remove worked. Its state stays "ready": the document is still
      // there, still counts toward the drawing-set gate, and can still
      // be retyped or removed again -- only `error` carries the failed
      // tone, in the same state column a failed upload or a failed
      // retype uses.
      update(row.key, { error: err.message });
    }
  };

  // A manual change turns off the "detected" hint -- the estimator owns
  // the value now. A persisted row writes through the API; a row still
  // uploading just changes the type it will finish uploading with, since
  // there's nothing to PATCH yet. A failed write-through reverts the
  // select rather than leaving it showing a type the server never
  // accepted, and surfaces the server's own message on the row.
  const setDocType = (row, docType) => {
    const previous = row.docType;
    update(row.key, { docType, typeAuto: false });
    // Gated on having a document id, not on `state === "ready"` -- a
    // row still uploading has neither yet, and its local change is
    // forwarded once the upload resolves and hands back an id (see the
    // upload's `.then` above). A persisted row -- "ready", or "ready"
    // carrying an `error` from an earlier failed write -- always has
    // one and writes through immediately.
    if (!row.id) return;
    store
      .setDocumentType(row.id, docType)
      .then(() => update(row.key, { error: undefined }))
      .catch((err) => {
        // The row stays "ready": one failed retype must not un-count an
        // already-uploaded document or disable retyping it again.
        update(row.key, { docType: previous, error: err.message });
      });
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
      {/* Same "Review detected drawings" control as the footer's, matching
          ConfirmDrawings' sticky-top-bar-plus-footer pair -- the top bar
          keeps the next step reachable without scrolling down to a long
          document list. Two controls sharing one accessible name is
          expected here, same as ConfirmDrawings.test.jsx: query with
          getAllByRole and check every match. */}
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
          {loadError ? (
            <div className="warncard warncard--missing" role="alert">
              <h4>
                <AlertTriangle aria-hidden="true" size={16} /> Couldn't load documents
              </h4>
              <p>Couldn't load this project's documents. Check the connection and try again.</p>
              <button type="button" className="btn" onClick={loadDocuments}>
                Try again
              </button>
            </div>
          ) : null}

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
                      {/* A live region per row, so a state that changes
                          after the estimator has moved on -- an upload
                          settling, a duplicate refused, a retype the
                          server would not take -- is announced rather
                          than appearing silently (WCAG 2.2 4.1.3). The
                          progress percentage is hidden from it: it
                          changes many times a second, and a live region
                          that re-announces every tick is one nobody
                          keeps switched on. "Uploading…" is announced
                          once; the number stays visual. */}
                      <td aria-live="polite" aria-atomic="true">
                        {/* row.error carries a failed retype or a failed
                            remove on an otherwise-ready row -- the row's
                            own state stays "ready" (it still counts, and
                            can still be acted on), so the failed tone has
                            to come from `error`'s presence rather than
                            from `state`. */}
                        <span className={`upload-status upload-status--${row.error ? STATE_TONE.failed : STATE_TONE[row.state]}`}>
                          {row.state === "uploading" ? (
                            <>
                              Uploading… <span aria-hidden="true" className="tabular">{row.progress}%</span>
                            </>
                          ) : row.error ? (
                            row.error
                          ) : row.state === "ready" ? (
                            "Uploaded"
                          ) : (
                            row.message
                          )}
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
