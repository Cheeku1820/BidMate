/* ============================================================
   ProcessingStatus.jsx — spec §5 screen E, minimal stub.

   The engine now runs behind the API (B2): this screen no longer
   fetches document bytes or drives the engine itself. On mount it asks
   the API what's already going (store.getProcessing) and, if nothing
   is running yet, starts one (store.startTakeoff). A run already in
   flight (`run_in_flight`) is treated as success, not an error -- the
   estimator gets the same "reading your drawings" state either way. A
   set with no readable drawings (`no_readable_drawings`) is the one
   failure worth naming specifically, with a way back to fix it.

   Tasks 13-15 replace this with the real per-sheet progress view (the
   documents/run shape store.getProcessing already returns); this stub
   exists only to keep the build green at this commit.
   ============================================================ */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";

export default function ProcessingStatus({ store }) {
  const { projectId } = useParams();

  const [mode, setMode] = useState("checking"); // checking | reading | error
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        const processing = await store.getProcessing(projectId);
        if (!alive) return;

        if (!processing.run) {
          try {
            await store.startTakeoff(projectId);
          } catch (err) {
            if (err?.code === "run_in_flight") {
              // Already running -- nothing more to do here.
            } else if (err?.code === "no_readable_drawings") {
              if (alive) {
                setError(err.message);
                setMode("error");
              }
              return;
            } else {
              throw err;
            }
          }
        }

        if (alive) setMode("reading");
      } catch (err) {
        if (!alive) return;
        setError(err?.message || "Couldn't load this project's processing status. Try again.");
        setMode("error");
      }
    })();

    return () => {
      alive = false;
    };
  }, [store, projectId]);

  return (
    <>
      <AppTopBar
        title="Processing"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={
          mode === "reading" ? (
            <Link className="btn btn--primary" to={`/projects/${projectId}/takeoff`}>
              Continue to review
            </Link>
          ) : null
        }
      />

      <div className="page">
        <h1 className="page-heading">{mode === "error" ? "Couldn't start processing" : "Reading your drawings"}</h1>

        {mode === "error" ? (
          <div className="load-error" role="alert">
            <p>{error}</p>
            <Link className="btn" to={`/projects/${projectId}/documents`}>
              Back to documents
            </Link>
          </div>
        ) : null}

        {mode === "reading" ? (
          <>
            <p className="muted">Sheets keep processing and are reviewable as they finish.</p>
            <div className="form-actions">
              <Link className="btn btn--primary" to={`/projects/${projectId}/takeoff`}>
                Continue to review
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
