/* ============================================================
   AppShell.jsx — the frame every signed-in screen renders inside.

   Holds the left rail and the outlet. It deliberately does not own the
   top bar: a company-level screen and a project workspace put different
   things in it, so each route renders its own AppTopBar rather than the
   shell guessing.

   One rail, not two. Inside a project the rail is the project sidebar;
   everywhere else it is the company nav. Stacking both would cost about
   250px of width on the one screen (spec §12: the blueprint stays the
   largest element in the review workspace) that can least afford it, and
   the way back out to company level is the top bar's breadcrumb, which
   every project screen carries.

   The rail is mounted here rather than by each screen, which is what it
   used to be. Five screens rendered ProjectNav themselves and the
   review workspaces rendered nothing, so an estimator lost the project
   navigation at exactly the point they were deepest inside a project.
   ============================================================ */

import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import CompanyNav from "./CompanyNav.jsx";
import ProjectNav from "./ProjectNav.jsx";
import { getCompanySettings } from "../../lib/settingsStore.js";

// /projects/:projectId and anything under it. "new" is excluded because
// /projects/new is the create form, which belongs to no project yet and
// would otherwise get a sidebar full of links to a project id that does
// not exist.
const PROJECT_ROUTE = /^\/projects\/(?!new(?:\/|$))([^/]+)/;

// Matches /projects/:anything/takeoff — see CompanyNav.jsx's identical
// constant and the width reasoning in styles.css.
const TAKEOFF_ROUTE = /^\/projects\/[^/]+\/takeoff(\/|$)/;

export function projectIdFromPath(pathname) {
  return PROJECT_ROUTE.exec(pathname)?.[1] ?? null;
}

export default function AppShell({ store = null }) {
  const { pathname } = useLocation();
  const projectId = projectIdFromPath(pathname);

  return (
    <div className="app-shell">
      {projectId ? (
        <ProjectRail key={projectId} projectId={projectId} store={store} isTakeoffRoute={TAKEOFF_ROUTE.test(pathname)} />
      ) : (
        <CompanyNav />
      )}
      <main className="app-shell-main">
        <Outlet />
      </main>
    </div>
  );
}

/* The project row behind the sidebar's header card. Loaded here rather
   than threaded down from each screen: the rail outlives every route
   change within a project, so fetching per screen would refetch the same
   row on every navigation.

   Defensive about `store` for the same reason ProjectWorkspaceLayout is:
   unit tests and any caller without listProjects simply get a sidebar
   with no header card, which is the correct degraded state rather than a
   crash. */
function ProjectRail({ projectId, store, isTakeoffRoute }) {
  const [project, setProject] = useState(null);
  const [collapsed, setCollapsed] = useState(isTakeoffRoute);

  // Re-derived when the route crosses the takeoff boundary, mirroring
  // CompanyNav.jsx: the rail stays mounted across in-app navigation, so
  // without this the default would only ever apply on a fresh load.
  useEffect(() => {
    setCollapsed(isTakeoffRoute);
  }, [isTakeoffRoute]);

  useEffect(() => {
    if (!store || typeof store.listProjects !== "function") return undefined;
    let alive = true;
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (alive) setProject(rows.find((row) => row.id === projectId) ?? null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [store, projectId]);

  return (
    <ProjectNav
      projectId={projectId}
      project={project}
      companyName={getCompanySettings().companyName?.value ?? null}
      collapsed={collapsed}
      onToggleCollapsed={() => setCollapsed((v) => !v)}
    />
  );
}
