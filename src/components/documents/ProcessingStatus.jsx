/* ============================================================
   ProcessingStatus.jsx — spec §5 screen E, driving the real engine.

   If the estimator uploaded drawings, this posts them to the takeoff
   engine (engineClient) and shows a genuine multi-stage loading sequence
   while the request is in flight, then ingests the result into the
   project's store (attachEngineTakeoff) and sends them to review. The
   stage labels are indicative -- the engine runs as one request -- but
   completion is real.

   With no upload, there is nothing to process -- this is an error state,
   not a fallback, since a project only reaches this screen after Upload
   documents requires a drawing set. Re-entering a project that already
   has a takeoff never re-runs.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { estimateProject } from "../../lib/engineClient.js";
import { getUploadedFiles, clearUploadedFiles } from "../../lib/uploadedFiles.js";

const ENGINE_STAGES = ["Uploading documents", "Reading drawings and specifications", "Counting devices", "Classifying and pricing"];

const money = (n) => "$" + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

// Module-level so StrictMode's double-invoked effect (and its cleanup)
// can't fire the engine twice: both invocations await the same in-flight
// request, and only the one still mounted applies the result.
const engineRuns = new Map(); // projectId -> Promise<payload>


export default function ProcessingStatus({ store }) {
  const { projectId } = useParams();

  const [mode, setMode] = useState("checking"); // checking | engine | done | error
  const [engineStage, setEngineStage] = useState(0);
  const [summary, setSummary] = useState(null);
  const [reviewPath, setReviewPath] = useState("");
  const [error, setError] = useState(null);
  // Set when the server refuses to replace a takeoff that holds
  // approvals. Carries the server's own message, which names the count —
  // the estimator is told what they would lose, not asked a vague
  // "are you sure".
  const [replaceConfirm, setReplaceConfirm] = useState(null);

  const attachTakeoff = useCallback(
    async (payload, { confirmReplace = false } = {}) => {
      try {
        await store.attachEngineTakeoff(projectId, payload, { confirmReplace });
        clearUploadedFiles(projectId);
        setReplaceConfirm(null);
        setReviewPath(`/projects/${projectId}/takeoff`);
        setMode("done");
      } catch (err) {
        if (err?.code === "approved_items_present") {
          setReplaceConfirm({ message: err.message, payload });
          setMode("confirm-replace");
          return;
        }
        throw err;
      }
    },
    [store, projectId],
  );

  // The confirm dialog's own retry. A rejection here can't fall back on
  // the mount effect's try/catch the way the first attempt does -- this is
  // what turns a second failure (network blip, a 500, a stale project)
  // into the same error state instead of an unhandled rejection that
  // leaves the estimator staring at a confirm button that looks broken.
  const confirmReplace = useCallback(async () => {
    if (!replaceConfirm) return;
    try {
      await attachTakeoff(replaceConfirm.payload, { confirmReplace: true });
    } catch (err) {
      setReplaceConfirm(null);
      setError(err?.message || "The takeoff couldn't be replaced.");
      setMode("error");
    }
  }, [attachTakeoff, replaceConfirm]);

  useEffect(() => {
    // `alive` is per-invocation and re-created here, so StrictMode's
    // mount→cleanup→mount cycle leaves the final invocation with alive=true
    // (the earlier one's cleanup only flips its own closure). The engine
    // call itself is deduped module-side (engineRuns), so it fires once.
    let alive = true;
    const timers = [];

    (async () => {
      let project = null;
      try {
        const rows = (await store.listProjects?.({ includeArchived: true })) ?? [];
        project = rows.find((p) => p.id === projectId) ?? null;
      } catch {
        project = null;
      }
      if (!alive) return;

      // Already has a takeoff — show complete, never re-run.
      if (project && project.hasTakeoff) {
        setReviewPath(`/projects/${projectId}/takeoff`);
        setMode("done");
        return;
      }

      const uploaded = getUploadedFiles(projectId);

      if (uploaded.length > 0) {
        // --- real engine path ---
        setMode("engine");
        let stage = 0;
        const iv = setInterval(() => {
          if (!alive) return;
          stage = Math.min(stage + 1, ENGINE_STAGES.length - 1);
          setEngineStage(stage);
        }, 2500);
        timers.push(() => clearInterval(iv));
        try {
          // Dedupe the network call across StrictMode's double invoke.
          let run = engineRuns.get(projectId);
          if (!run) {
            run = estimateProject(uploaded, project?.location || "");
            engineRuns.set(projectId, run);
          }
          const payload = await run;
          engineRuns.delete(projectId);
          if (!alive) return;
          clearInterval(iv);
          setSummary({
            items: payload.totals.item_count,
            total: payload.totals.total_direct_cost,
            sheets: payload.sheets.length,
            location: payload.location,
            source: payload.source,
          });
          await attachTakeoff(payload);
        } catch (err) {
          engineRuns.delete(projectId); // let a retry start fresh
          if (!alive) return;
          clearInterval(iv);
          setError(err.message);
          setMode("error");
        }
        return;
      }

      // No documents uploaded — there is nothing to process.
      setError("No documents have been uploaded for this project yet. Upload a drawing set to start a takeoff.");
      setMode("error");
    })();

    return () => {
      alive = false;
      timers.forEach((t) => (typeof t === "function" ? t() : clearTimeout(t)));
    };
  }, [store, projectId]);

  const heading =
    mode === "done"
      ? "Processing complete"
      : mode === "error"
        ? "Couldn't finish processing"
        : "Reading your drawings";

  return (
    <>
      <AppTopBar
        title="Processing"
        breadcrumb={[{ label: "Projects", to: "/projects" }, { label: "Documents" }]}
        primaryAction={
          mode === "done" && reviewPath ? (
            <Link className="btn btn--primary" to={reviewPath}>
              Continue to review
            </Link>
          ) : null
        }
      />

      <div className="page">
        <h1 className="page-heading">{heading}</h1>

        {mode === "error" ? (
          <div className="load-error" role="alert">
            <p>{error}</p>
            <Link className="btn" to={`/projects/${projectId}/documents`}>
              Back to documents
            </Link>
          </div>
        ) : null}

        {mode === "confirm-replace" && replaceConfirm ? (
          <div className="processing-confirm" role="alertdialog" aria-labelledby="replace-confirm-title">
            <h2 id="replace-confirm-title">Replacing this takeoff discards approved items</h2>
            <p>{replaceConfirm.message}</p>
            <p>
              Approving an item is a record that a person checked it. Replacing the takeoff removes those records
              along with the items.
            </p>
            <div className="processing-confirm-actions">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setReplaceConfirm(null);
                  setReviewPath(`/projects/${projectId}/takeoff`);
                  setMode("done");
                }}
              >
                Keep the current takeoff
              </button>
              <button type="button" className="btn btn--danger" onClick={confirmReplace}>
                Replace the takeoff
              </button>
            </div>
          </div>
        ) : null}

        {mode === "engine" ? (
          <>
            <p className="muted">
              This can take a moment on a large set — the last step reads the drawings with the model. You can leave
              this page.
            </p>
            <ul className="processing-list">
              {ENGINE_STAGES.map((label, idx) => {
                const complete = idx < engineStage;
                const active = idx === engineStage;
                return (
                  <li key={label} className="processing-row">
                    <span className="processing-icon" aria-hidden="true">
                      {complete ? (
                        <CheckCircle2 size={18} className="ink-blue" />
                      ) : active ? (
                        <Loader2 size={18} className="spin" />
                      ) : (
                        <span className="processing-dot" />
                      )}
                    </span>
                    <span className="processing-title">{label}</span>
                    <span className="processing-stage">{complete ? "Done" : active ? "Working…" : "Waiting"}</span>
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}

        {mode === "done" ? (
          <>
            <p className="muted">
              {summary
                ? `${summary.sheets} electrical sheet${summary.sheets === 1 ? "" : "s"} read, ${summary.items} line items, ${money(summary.total)} total direct cost${summary.location ? " for " + summary.location : ""}. Continue to review.`
                : "Every sheet finished. Continue to review the takeoff."}
            </p>
            <div className="form-actions">
              <Link className="btn btn--primary" to={reviewPath || `/projects/${projectId}`}>
                Continue to review
              </Link>
              <Link className="btn" to={`/projects/${projectId}`}>
                Back to project
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
