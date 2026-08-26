/* ============================================================
   ProcessingStatus.jsx — spec §5 screen E, the processing wait.

   In seed mode there is no engine, so this simulates the pipeline
   walking each sheet through descriptive stages and then stands a sample
   takeoff into the project (seed.js's attachSampleTakeoff). Spec §5's
   rules that DO carry, engine or not:

     - Descriptive stages, never a fabricated precise time remaining.
     - "You can leave this page" -- the work is saved.
     - Completed sheets stay visible even if another sheet needs
       attention; a per-sheet outcome is honest about that sheet alone.

   Re-entering this screen for an already-processed project does not
   re-run and wipe review progress: it detects the attached sample and
   goes straight to the completed state.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { CheckCircle2, Loader2 } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";

// The stage a sheet is in. Index 0..STAGES.length-1 while working, then
// "complete". Descriptive, per spec §5 -- no percentage, no ETA.
const STAGES = ["Waiting", "Reading sheet", "Finding electrical items", "Checking schedules"];

const SAMPLE_SHEETS = [
  { id: "e11", number: "E1.1", title: "Level 1 power" },
  { id: "e21", number: "E2.1", title: "Warehouse power" },
  { id: "e31", number: "E3.1", title: "Roof and site" },
];

export default function ProcessingStatus({ store }) {
  const { projectId } = useParams();
  const navigate = useNavigate();

  // Per-sheet stage index; -1 means complete.
  const [progress, setProgress] = useState(() => SAMPLE_SHEETS.map(() => 0));
  const [done, setDone] = useState(false);
  const attachedRef = useRef(false);

  useEffect(() => {
    let alive = true;
    const timers = [];

    // If this project already carries a sample takeoff, re-processing
    // would overwrite the estimator's review progress. Detect that and
    // show the completed state instead of running again.
    (async () => {
      let alreadySampled = false;
      try {
        const rows = (await store.listProjects?.({ includeArchived: true })) ?? [];
        alreadySampled = rows.find((p) => p.id === projectId)?.sample === true;
      } catch {
        alreadySampled = false;
      }
      if (!alive) return;

      if (alreadySampled) {
        setProgress(SAMPLE_SHEETS.map(() => -1));
        setDone(true);
        return;
      }

      // Simulate each sheet advancing through the stages, staggered so
      // they don't all move in lockstep.
      SAMPLE_SHEETS.forEach((_, sheetIdx) => {
        for (let stage = 1; stage <= STAGES.length; stage += 1) {
          const at = 500 + sheetIdx * 300 + stage * 550;
          timers.push(
            setTimeout(() => {
              if (!alive) return;
              setProgress((prev) => {
                const next = prev.slice();
                next[sheetIdx] = stage >= STAGES.length ? -1 : stage;
                return next;
              });
            }, at),
          );
        }
      });

      // When the last sheet finishes, attach the sample and reveal the
      // continue action. Ref-guarded so StrictMode's double-invoke can't
      // attach twice.
      const finishAt = 500 + (SAMPLE_SHEETS.length - 1) * 300 + STAGES.length * 550 + 300;
      timers.push(
        setTimeout(async () => {
          if (!alive || attachedRef.current) return;
          attachedRef.current = true;
          try {
            await store.attachSampleTakeoff?.(projectId);
          } catch {
            // A failed attach is non-fatal here; the continue action
            // below still routes to the workspace, which shows its own
            // empty state honestly if nothing landed.
          }
          if (alive) setDone(true);
        }, finishAt),
      );
    })();

    return () => {
      alive = false;
      timers.forEach(clearTimeout);
    };
  }, [store, projectId]);

  const stageLabel = (idx) => (idx === -1 ? "Complete" : STAGES[idx]);

  return (
    <>
      <AppTopBar
        title="Processing"
        primaryAction={
          done ? (
            <Link className="btn btn--primary" to={`/projects/${projectId}/takeoff`}>
              Continue to review
            </Link>
          ) : null
        }
      />
      <ProjectNav projectId={projectId} />

      <div className="page">
        <h1 className="page-heading">{done ? "Processing complete" : "Reading your drawings"}</h1>
        <p className="muted">
          {done
            ? "Every sheet finished. Continue to review the takeoff."
            : "This can take a few minutes on a large set. You can leave this page — your progress is saved."}
        </p>

        <ul className="processing-list">
          {SAMPLE_SHEETS.map((sheet, idx) => {
            const complete = progress[idx] === -1;
            return (
              <li key={sheet.id} className="processing-row">
                <span className="processing-icon" aria-hidden="true">
                  {complete ? <CheckCircle2 size={18} className="ink-blue" /> : <Loader2 size={18} className="spin" />}
                </span>
                <span className="processing-sheet tabular">{sheet.number}</span>
                <span className="processing-title">{sheet.title}</span>
                <span className={complete ? "processing-stage is-complete" : "processing-stage"}>{stageLabel(progress[idx])}</span>
              </li>
            );
          })}
        </ul>

        {done ? (
          <div className="form-actions">
            <Link className="btn btn--primary" to={`/projects/${projectId}/takeoff`}>
              Continue to review
            </Link>
            <Link className="btn" to={`/projects/${projectId}`}>
              Back to project
            </Link>
          </div>
        ) : null}
      </div>
    </>
  );
}
