/* ============================================================
   ProcessingStatus.jsx — spec §5 screen E, "processing status".

   A view onto store.getProcessing: every sheet in the run with the
   stage it is at, the documents the worker couldn't read, and a way
   into the review workspace the moment the first sheet is complete --
   each sheet is reviewable as it finishes, so nobody waits for the
   last one. The list itself is SheetProgressList.jsx, shared with the
   notes screen's re-run so a run reads the same way wherever it is
   watched.

   On mount the screen asks what is already going. If no run exists it
   starts one itself (store.startTakeoff): screen D's "Start takeoff"
   already asked for it, and landing here is the estimator's intent
   either way, so there is no second button to press. A run already in
   flight (`run_in_flight`) is the outcome wanted, not an error. A set
   with nothing readable (`no_readable_drawings`) is the one refusal
   worth naming, with the server's own words and a way back to fix the
   documents -- and nothing to poll, since there is no run.

   While the run is queued or running the screen polls every few
   seconds (the same cadence screens C and D use) and stops the moment
   the run reaches a terminal state, or the screen unmounts. A poll
   that fails is left alone: the last state stays on screen and the
   next tick tries again -- a blip in the connection is not news the
   estimator needs while the sheets are still being read.

   A run that finished with failures says so in words, with the count
   of sheets needing attention in the heading and each one's reason
   beneath its row. When the run's own reason is set -- it failed
   before any sheet was worked -- that reason is the alert, because
   the sheets never got a stage of their own to explain it.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import SheetProgressList from "./SheetProgressList.jsx";

// How often to ask again while the run is going. Matches screens C
// and D; nothing here needs to be faster than the worker.
export const RUN_POLL_MS = 3000;

const LEAVE_COPY = "You can leave this page. Sheets keep processing and are reviewable as they finish.";

export function isRunActive(run) {
  return run == null || run.state === "queued" || run.state === "running";
}

function attentionCount(run) {
  return run.sheets.filter((s) => s.stage === "attention").length;
}

/** The heading for a run in a given state, in words an estimator
 *  reads without a glossary.
 *
 *  Sheets needing attention are counted before the run's own state is
 *  read: a sheet unreadable at read time never gets a job of its own,
 *  so a run made only of such sheets reports `complete` while every
 *  row says *Needs attention* (api/app/jobs/status.py). "Processing
 *  complete" over that list would be silence reading as completeness,
 *  so the count decides. `complete_with_failures` with no such sheet
 *  is the run failing before any sheet was worked; its reason is the
 *  alert, and the heading says only that it didn't finish. */
export function runHeading(run) {
  if (isRunActive(run)) return "Reading your drawings";
  const n = attentionCount(run);
  if (n > 0) return `Processing finished with ${n} ${n === 1 ? "sheet" : "sheets"} needing attention`;
  if (run.state === "complete") return "Processing complete";
  return "Processing couldn't finish";
}

export default function ProcessingStatus({ store }) {
  const { projectId } = useParams();

  // mode: loading (first fetch) | active (a run is or will be going,
  // poll it) | blocked (no run could start; the server said why) |
  // error (couldn't load at all)
  const [mode, setMode] = useState("loading");
  const [error, setError] = useState("");
  const [processing, setProcessing] = useState(null);

  // Sticks at false once the component unmounts, so a result landing
  // late is a no-op rather than a set-state-after-unmount. Re-armed in
  // the effect body, not only in its cleanup -- StrictMode's simulated
  // mount/unmount/remount runs the cleanup once in development.
  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    (async () => {
      try {
        let current = await store.getProcessing(projectId);
        if (!aliveRef.current) return;

        if (!current.run) {
          try {
            await store.startTakeoff(projectId);
          } catch (err) {
            if (err?.code === "run_in_flight") {
              // Already going -- the outcome wanted.
            } else if (err?.code === "no_readable_drawings") {
              if (!aliveRef.current) return;
              setProcessing(current);
              setError(err.message);
              setMode("blocked");
              return;
            } else {
              throw err;
            }
          }
          // The run was just asked for; ask again so the queued sheets
          // show without waiting a full poll interval. A failure here
          // is the poll's problem, not the start's.
          try {
            current = await store.getProcessing(projectId);
          } catch {
            // keep `current`
          }
          if (!aliveRef.current) return;
        }

        setProcessing(current);
        setMode("active");
      } catch (err) {
        if (!aliveRef.current) return;
        setError(err?.message || "Couldn't load this project's processing status. Try again.");
        setMode("error");
      }
    })();
  }, [store, projectId]);

  // Poll while the run is going; stop the moment it is not. Keyed on
  // the boolean so the interval restarts only when the run starts or
  // stops, not on every unrelated state change. Cleared on unmount.
  const polling = mode === "active" && isRunActive(processing?.run);
  useEffect(() => {
    if (!polling) return undefined;
    const tick = () => {
      store
        .getProcessing(projectId)
        .then((next) => {
          if (!aliveRef.current) return;
          setProcessing(next);
        })
        .catch(() => {});
    };
    const interval = setInterval(tick, RUN_POLL_MS);
    return () => clearInterval(interval);
  }, [polling, store, projectId]);

  const run = processing?.run ?? null;
  const reviewable = mode === "active" && run != null && run.completeCount >= 1;
  const finished = mode === "active" && run != null && !isRunActive(run);
  const runFailed = finished && run.state === "complete_with_failures" && run.reason;

  const reviewLink = (
    <Link className="btn btn--primary" to={`/projects/${projectId}/takeoff`}>
      Continue to review
    </Link>
  );

  let heading = "Reading your drawings";
  if (mode === "error") heading = "Couldn't load processing";
  else if (mode === "blocked") heading = "Couldn't start processing";
  else if (mode === "active") heading = runHeading(run);

  return (
    <>
      <AppTopBar
        title="Processing"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={reviewable ? reviewLink : null}
      />

      <div className="page">
        <h1 className="page-heading">{heading}</h1>

        {mode === "loading" ? <p className="muted">Loading…</p> : null}

        {mode === "error" || mode === "blocked" ? (
          <div className="load-error" role="alert">
            <p>{error}</p>
            <Link className="btn" to={`/projects/${projectId}/documents`}>
              Back to documents
            </Link>
          </div>
        ) : null}

        {runFailed ? (
          <div className="warncard warncard--missing" role="alert">
            <p>{run.reason}</p>
          </div>
        ) : null}

        {mode === "active" && !finished ? <p className="muted">{LEAVE_COPY}</p> : null}

        {mode === "active" || mode === "blocked" ? (
          <SheetProgressList run={run} documents={processing?.documents ?? []} />
        ) : null}

        {finished ? (
          <div className="form-actions">
            {reviewable ? reviewLink : null}
            <Link className="btn" to={`/projects/${projectId}/documents`}>
              Back to documents
            </Link>
          </div>
        ) : null}
      </div>
    </>
  );
}
