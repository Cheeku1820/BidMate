/* ============================================================
   ProcessingStatus.jsx — spec §5 screen E, now driving the real engine.

   If the estimator uploaded drawings, this posts them to the takeoff
   engine (engineClient) and shows a genuine multi-stage loading sequence
   while the request is in flight, then ingests the result into the
   project's store (attachEngineTakeoff) and sends them to review. The
   stage labels are indicative -- the engine runs as one request -- but
   completion is real.

   With no upload (the sample demo path), it keeps the simulated per-sheet
   animation and stands in a sample takeoff, so that path still works.
   Re-entering a project that already has a takeoff never re-runs.
   ============================================================ */

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { CheckCircle2, Loader2, AlertTriangle } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";
import { estimateProject } from "../../lib/engineClient.js";
import { getUploadedFiles, clearUploadedFiles } from "../../lib/uploadedFiles.js";

const ENGINE_STAGES = ["Uploading documents", "Reading drawings and specifications", "Counting devices", "Classifying and pricing"];

const SAMPLE_SHEETS = [
  { id: "e11", number: "E1.1", title: "Level 1 power" },
  { id: "e21", number: "E2.1", title: "Warehouse power" },
  { id: "e31", number: "E3.1", title: "Roof and site" },
];

const money = (n) => "$" + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

// Module-level so StrictMode's double-invoked effect (and its cleanup)
// can't fire the engine twice: both invocations await the same in-flight
// request, and only the one still mounted applies the result.
const engineRuns = new Map(); // projectId -> Promise<payload>


export default function ProcessingStatus({ store }) {
  const { projectId } = useParams();

  const [mode, setMode] = useState("checking"); // checking | engine | sample | done | error
  const [engineStage, setEngineStage] = useState(0);
  const [sampleProgress, setSampleProgress] = useState(() => SAMPLE_SHEETS.map(() => 0));
  const [summary, setSummary] = useState(null);
  const [reviewPath, setReviewPath] = useState("");
  const [error, setError] = useState(null);

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
      if (project && (project.sample || project.hasTakeoff)) {
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
          await store.attachEngineTakeoff(projectId, payload);
          clearUploadedFiles(projectId);
          clearInterval(iv);
          setSummary({
            items: payload.totals.item_count,
            total: payload.totals.total_direct_cost,
            sheets: payload.sheets.length,
            location: payload.location,
            source: payload.source,
          });
          setReviewPath(`/projects/${projectId}/takeoff`);
          setMode("done");
        } catch (err) {
          engineRuns.delete(projectId); // let a retry start fresh
          if (!alive) return;
          clearInterval(iv);
          setError(err.message);
          setMode("error");
        }
        return;
      }

      // --- sample fallback (no upload) ---
      setMode("sample");
      SAMPLE_SHEETS.forEach((_, sheetIdx) => {
        for (let s = 1; s <= 3; s += 1) {
          timers.push(
            setTimeout(() => {
              if (!alive) return;
              setSampleProgress((prev) => {
                const next = prev.slice();
                next[sheetIdx] = s >= 3 ? -1 : s;
                return next;
              });
            }, 400 + sheetIdx * 250 + s * 450),
          );
        }
      });
      timers.push(
        setTimeout(async () => {
          if (!alive) return;
          try {
            await store.attachSampleTakeoff?.(projectId);
          } catch {
            /* non-fatal */
          }
          if (!alive) return;
          setReviewPath(`/projects/${projectId}/takeoff`);
          setMode("done");
        }, 400 + SAMPLE_SHEETS.length * 250 + 3 * 450 + 300),
      );
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
        primaryAction={
          mode === "done" && reviewPath ? (
            <Link className="btn btn--primary" to={reviewPath}>
              Continue to review
            </Link>
          ) : null
        }
      />
      <ProjectNav projectId={projectId} />

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

        {mode === "sample" ? (
          <>
            <p className="muted">You can leave this page — your progress is saved.</p>
            <ul className="processing-list">
              {SAMPLE_SHEETS.map((sheet, idx) => {
                const complete = sampleProgress[idx] === -1;
                return (
                  <li key={sheet.id} className="processing-row">
                    <span className="processing-icon" aria-hidden="true">
                      {complete ? <CheckCircle2 size={18} className="ink-blue" /> : <Loader2 size={18} className="spin" />}
                    </span>
                    <span className="processing-sheet tabular">{sheet.number}</span>
                    <span className="processing-title">{sheet.title}</span>
                    <span className={complete ? "processing-stage is-complete" : "processing-stage"}>
                      {complete ? "Complete" : "Reading sheet"}
                    </span>
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
