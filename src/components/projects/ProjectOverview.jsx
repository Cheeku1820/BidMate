/* ============================================================
   ProjectOverview.jsx — spec §6.2, the project home and return point.

   Every card links to the records behind it, per the spec. The warning
   copy states the consequence rather than a count alone: "2 items are
   missing required information" tells an estimator what it will do to
   them at finish-review, which a bare number does not.

   Date formatting comes from lib/format.js's formatCalendarDate, the
   same UTC-anchored formatter ProjectsDashboard.jsx uses for
   bidDueDate -- a second, locally-defined formatDate() here would
   reintroduce the UTC-midnight-parses-a-day-early bug that formatter
   exists to fix, for the same date-only field.

   Two failure states, kept apart. A `listProjects()` network failure and
   a genuinely absent project are different facts and read differently:
   nothing was archived when the request simply failed, so the two get
   distinct copy and only the load failure gets a retry -- mirroring
   ProjectsDashboard.jsx's own error/empty split, which this screen did
   not originally have (task-8 review finding 2).
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";
import { reviewProgress, stageLabel } from "../../lib/projectStage.js";
import { formatCalendarDate, NOT_SET } from "../../lib/format.js";

export default function ProjectOverview({ store }) {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [state, setState] = useState("loading");
  const [errorMessage, setErrorMessage] = useState(null);

  // Re-armed at the top of the effect body, not just initialised once --
  // see ProjectsDashboard.jsx's identical comment. src/main.jsx renders
  // the app inside <React.StrictMode>, which in development
  // double-invokes every mount effect (run, cleanup, run again)
  // synchronously before any pending promise settles. A ref that only
  // ever gets set back to true when first created would be permanently
  // tripped by the first run's cleanup, and the second run's
  // listProjects() resolution would be silently dropped -- the screen
  // would hang on "Loading project…" forever under `npm run dev` even
  // though the fetch succeeded.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // A stable callback, not inlined in the effect, so the "Try again"
  // button below can call the exact same load path a mount does --
  // ProjectsDashboard.jsx's load()/retry pattern.
  const load = useCallback(() => {
    setState("loading");
    setErrorMessage(null);
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (!mountedRef.current) return;
        const found = rows.find((row) => row.id === projectId);
        setProject(found ?? null);
        setState(found ? "ready" : "missing");
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        setErrorMessage(err?.message || "The project couldn't be loaded. Try again.");
        setState("error");
      });
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  if (state === "loading") return <p className="muted page">Loading project…</p>;

  if (state === "error") {
    return (
      <div className="page">
        <div className="load-error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" className="btn" onClick={load}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (state !== "ready" || !project) {
    return (
      <div className="empty-state">
        <h1>That project isn't available</h1>
        <p>It may have been archived, or the link may be out of date.</p>
        <Link className="btn btn--primary" to="/projects">
          Back to projects
        </Link>
      </div>
    );
  }

  const progress = reviewProgress(project);
  // A project with no items has no takeoff to continue reviewing --
  // "Continue review" (or the review-progress card's own link below)
  // would otherwise be the single most prominent thing to click right
  // after creating a project, and following it lands on a workspace with
  // markers and a scale banner belonging to a *different* project (seed
  // mode's single fixture snapshot today; a real ingestion pipeline
  // tomorrow, before its first sheet finishes processing). That is a
  // fabricated quantity presented as this project's evidence. Upload
  // isn't built yet either, so the honest replacement says that plainly
  // rather than linking somewhere that pretends otherwise.
  const hasTakeoff = progress.total > 0;

  return (
    <>
      <AppTopBar
        title={project.name}
        subtitle={project.revisionSetLabel || "No drawing set yet"}
        primaryAction={
          hasTakeoff ? (
            <Link className="btn btn--primary" to={`/projects/${project.id}/takeoff`}>
              Continue review
            </Link>
          ) : (
            <span className="muted">Document upload isn't built yet</span>
          )
        }
      />
      <ProjectNav projectId={project.id} />

      <div className="page">
        <h1 className="page-heading">{project.name}</h1>

        <div className="card-grid">
          <section className="card">
            <h2>Project details</h2>
            <dl className="detail-list">
              <dt>Customer</dt>
              <dd>{project.customer || NOT_SET}</dd>
              <dt>Location</dt>
              <dd>{project.location || NOT_SET}</dd>
              <dt>Internal number</dt>
              <dd className="tabular">{project.number || NOT_SET}</dd>
              <dt>Bid due</dt>
              <dd className="tabular">{formatCalendarDate(project.bidDueDate)}</dd>
              <dt>Assigned estimator</dt>
              <dd>{project.estimatorName || NOT_SET}</dd>
            </dl>
          </section>

          <section className="card">
            <h2>Review progress</h2>
            <p className="tabular">
              {progress.total === 0
                ? "No items yet. Upload a drawing set to begin."
                : `${progress.approved} of ${progress.total} approved`}
            </p>
            <p className="muted">Current stage: {stageLabel(project.stage)}</p>
            {hasTakeoff ? (
              <Link to={`/projects/${project.id}/takeoff`}>Open the blueprint takeoff</Link>
            ) : null}
          </section>

          <section className="card">
            <h2>Unresolved</h2>
            {/* The count and the sentence around it share one text node
                rather than splitting the number into its own <span> --
                tabular-nums applies to the whole sentence with no visible
                effect on the letters, and it keeps the consequence
                ("these block finishing the review") readable as one
                statement instead of two fragments either side of an
                inline element. */}
            {project.missingInfo > 0 ? (
              <p className="tabular">
                {project.missingInfo} {project.missingInfo === 1 ? "item is" : "items are"} missing required
                information. These block finishing the review.
              </p>
            ) : null}
            {project.warningsOpen > 0 ? (
              <p className="tabular">
                {project.warningsOpen} {project.warningsOpen === 1 ? "item needs" : "items need"} attention
                before they can be approved.
              </p>
            ) : null}
            {project.missingInfo === 0 && project.warningsOpen === 0 ? <p>Nothing outstanding.</p> : null}
          </section>
        </div>
      </div>
    </>
  );
}
