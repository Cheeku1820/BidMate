/* ============================================================
   ProjectsDashboard.jsx — spec §5.1, screen A.

   A familiar table, deliberately: the estimator's existing tool is a
   spreadsheet, and the first screen of a new product is the wrong place
   to teach a new layout. Progress reads as text ("103 of 412 approved")
   rather than as a bar alone -- a bar is colour without a label, which
   CLAUDE.md rules out, and it is also unreadable in a grayscale print.

   The warnings column keeps "missing information" (red, blocking) and
   "needs attention" (amber, acknowledgeable) as two separate counts
   rather than one merged number. Blending them would let a project with
   two blocking missing-information items read the same as one with six
   soft needs-attention items, which is exactly the vocabulary blur
   CLAUDE.md's status spine exists to prevent.

   The brief's illustrative error path called window.location.reload() —
   a blunt instrument that would discard everything else on the page.
   This instead keeps a real retry that re-runs listProjects, per this
   task's stated ambiguity resolution.
   ============================================================ */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, AlertTriangle } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import ProjectsFilters from "./ProjectsFilters.jsx";
import { matchesFilter, reviewProgress, stageLabel } from "../../lib/projectStage.js";

const NOT_SET = "Not set";

/** `bidDueDate` is a calendar date with no time component
 *  ("2026-09-14") -- it has to read as the same date for every viewer
 *  regardless of their timezone, the way a deadline printed on a bid
 *  form would. `new Date(iso)` on a date-only string parses as UTC
 *  midnight per the ECMAScript spec, so formatting that instant in the
 *  viewer's local zone with no `timeZone` override renders it a day
 *  early in every zone behind UTC -- every US timezone, and therefore
 *  this product's whole user base. Anchoring the formatter itself to
 *  UTC keeps the calendar date stable no matter where the browser is.
 *  Do not fold this back into formatTimestamp below to "simplify" it —
 *  a timestamp needs the opposite behavior. */
function formatCalendarDate(iso) {
  if (!iso) return NOT_SET;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** `updatedAt` is a full timestamp ("2026-08-17T18:00:00Z"), an actual
 *  instant rather than a calendar date -- it should render in the
 *  viewer's own local zone, so no `timeZone` override here, on
 *  purpose. */
function formatTimestamp(iso) {
  if (!iso) return NOT_SET;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function compare(a, b, sort) {
  switch (sort) {
    case "bidDate":
      // Projects with no bid date sort last rather than first: an absent
      // deadline is not an imminent one.
      if (!a.bidDueDate) return b.bidDueDate ? 1 : 0;
      if (!b.bidDueDate) return -1;
      return a.bidDueDate.localeCompare(b.bidDueDate);
    case "name":
      return a.name.localeCompare(b.name);
    case "customer":
      return (a.customer || "").localeCompare(b.customer || "");
    case "estimator":
      return (a.estimatorName || "").localeCompare(b.estimatorName || "");
    default:
      return (b.updatedAt || "").localeCompare(a.updatedAt || "");
  }
}

export default function ProjectsDashboard({ store }) {
  const [projects, setProjects] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("active");
  const [sort, setSort] = useState("updated");

  // A single mounted-ness guard shared by every call to load(), not a
  // per-call `cancelled` closure wired only into the mount effect's
  // cleanup: the "Try again" retry button calls load() directly, and a
  // closure-per-call guard would only ever protect the mount-time call,
  // letting a retry that resolves after unmount set state on a dead
  // component.
  //
  // The re-arm on the first line is not redundant, even though the ref
  // already starts `true`. src/main.jsx renders the app inside
  // <React.StrictMode>, which in development deliberately double-invokes
  // every mount effect -- run, cleanup, run again -- synchronously,
  // before any pending promise has settled. Without re-arming here, the
  // first run's cleanup sets mountedRef.current = false and the second
  // run's body never sets it back to true, so it stays false forever
  // and listProjects()'s eventual resolution is silently dropped: the
  // dashboard hangs on "Loading projects..." under `npm run dev` even
  // though the fetch succeeded. Do not delete this line to "simplify"
  // it back to a plain useRef(true) initializer.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(() => {
    setError(null);
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (mountedRef.current) setProjects(rows);
      })
      .catch((err) => {
        if (mountedRef.current) {
          setError(err?.message || "The project list couldn't be loaded. Try again.");
        }
      });
  }, [store]);

  useEffect(() => {
    load();
  }, [load]);

  const visible = useMemo(() => {
    if (!projects) return [];
    const needle = search.trim().toLowerCase();
    return projects
      .filter((project) => matchesFilter(project, filter))
      .filter((project) => {
        if (!needle) return true;
        return [project.name, project.number, project.customer]
          .filter(Boolean)
          .some((field) => field.toLowerCase().includes(needle));
      })
      .sort((a, b) => compare(a, b, sort));
  }, [projects, search, filter, sort]);

  const hasProjects = Boolean(projects?.length);

  const newProjectLink = (
    <Link className="btn btn--primary" to="/projects/new">
      New project
    </Link>
  );

  return (
    <>
      {/* Shown only once there is already at least one project: while the
          list is empty, the empty state below carries its own "New
          project" call to action, and showing it here too would put two
          controls with the same accessible name on one screen. */}
      <AppTopBar title="Projects" primaryAction={hasProjects ? newProjectLink : undefined} />

      <div className="page">
        <h1 className="page-heading">Projects</h1>

        {error ? (
          <div className="load-error" role="alert">
            <p>{error}</p>
            <button type="button" className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : null}

        {projects === null && !error ? <p className="muted">Loading projects…</p> : null}

        {projects && projects.length === 0 ? (
          <div className="empty-state">
            <h2>Create your first estimate</h2>
            <p>Start a project, then upload the drawing set and specifications for the bid.</p>
            {newProjectLink}
          </div>
        ) : null}

        {hasProjects ? (
          <>
            <ProjectsFilters
              search={search}
              onSearch={setSearch}
              filter={filter}
              onFilter={setFilter}
              sort={sort}
              onSort={setSort}
            />

            {visible.length === 0 ? (
              <div className="empty-state">
                <h2>No projects match</h2>
                <p>Try a different search or filter.</p>
                <button type="button" className="btn" onClick={() => setSearch("")}>
                  Clear search
                </button>
              </div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Project</th>
                    <th scope="col">Customer</th>
                    <th scope="col">Location</th>
                    <th scope="col">Bid due</th>
                    <th scope="col">Estimator</th>
                    <th scope="col">Stage</th>
                    <th scope="col">Progress</th>
                    <th scope="col">Warnings</th>
                    <th scope="col">Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((project) => {
                    const progress = reviewProgress(project);
                    const missingInfo = project.missingInfo ?? 0;
                    const warningsOpen = project.warningsOpen ?? 0;
                    return (
                      <tr key={project.id}>
                        <th scope="row">
                          <Link to={`/projects/${project.id}`}>{project.name}</Link>
                          {project.number ? (
                            <span className="row-secondary tabular">{project.number}</span>
                          ) : null}
                        </th>
                        <td>{project.customer || NOT_SET}</td>
                        <td>{project.location || NOT_SET}</td>
                        <td className="tabular">{formatCalendarDate(project.bidDueDate)}</td>
                        <td>{project.estimatorName || NOT_SET}</td>
                        <td>{stageLabel(project.stage)}</td>
                        <td className="tabular">
                          {progress.total === 0
                            ? "Not started"
                            : `${progress.approved} of ${progress.total} approved`}
                        </td>
                        <td>
                          {missingInfo === 0 && warningsOpen === 0 ? (
                            "None"
                          ) : (
                            <div className="warning-summary">
                              {missingInfo > 0 ? (
                                <span className="warning-summary__row warning-summary__row--missing">
                                  <AlertCircle size={13} aria-hidden="true" />
                                  <span className="tabular">{missingInfo}</span>
                                  &nbsp;missing information
                                </span>
                              ) : null}
                              {warningsOpen > 0 ? (
                                <span className="warning-summary__row warning-summary__row--attention">
                                  <AlertTriangle size={13} aria-hidden="true" />
                                  <span className="tabular">{warningsOpen}</span>
                                  &nbsp;needs attention
                                </span>
                              ) : null}
                            </div>
                          )}
                        </td>
                        <td className="tabular">{formatTimestamp(project.updatedAt)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </>
        ) : null}
      </div>
    </>
  );
}
