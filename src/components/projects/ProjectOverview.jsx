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
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectNav from "../shell/ProjectNav.jsx";
import { reviewProgress, stageLabel } from "../../lib/projectStage.js";
import { formatCalendarDate } from "../../lib/format.js";

export default function ProjectOverview({ store }) {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [state, setState] = useState("loading");

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

  useEffect(() => {
    setState("loading");
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (!mountedRef.current) return;
        const found = rows.find((row) => row.id === projectId);
        setProject(found ?? null);
        setState(found ? "ready" : "missing");
      })
      .catch(() => {
        if (mountedRef.current) setState("error");
      });
  }, [store, projectId]);

  if (state === "loading") return <p className="muted page">Loading project…</p>;

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

  return (
    <>
      <AppTopBar
        title={project.name}
        subtitle={project.revisionSetLabel || "No drawing set yet"}
        primaryAction={
          <Link className="btn btn--primary" to={`/projects/${project.id}/takeoff`}>
            Continue review
          </Link>
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
              <dd>{project.customer || "Not set"}</dd>
              <dt>Location</dt>
              <dd>{project.location || "Not set"}</dd>
              <dt>Internal number</dt>
              <dd className="tabular">{project.number || "Not set"}</dd>
              <dt>Bid due</dt>
              <dd className="tabular">{formatCalendarDate(project.bidDueDate)}</dd>
              <dt>Assigned estimator</dt>
              <dd>{project.estimatorName || "Not assigned"}</dd>
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
            <Link to={`/projects/${project.id}/takeoff`}>Open the blueprint takeoff</Link>
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
