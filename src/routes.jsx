/* ============================================================
   routes.jsx — one place that knows what URLs exist.

   Adding a workspace is a row here plus a component, not a change in
   four files. Screens that spec §1 lists but that are not built yet
   deliberately do not appear: a nav entry leading to an empty page is
   worse than one that is not there, and spec §20 requires error copy to
   name a recovery action.
   ============================================================ */

import { Navigate, Route } from "react-router-dom";
import AppShell from "./components/shell/AppShell.jsx";
import ProjectsDashboard from "./components/projects/ProjectsDashboard.jsx";
import NewProject from "./components/projects/NewProject.jsx";
import ProjectOverview from "./components/projects/ProjectOverview.jsx";
import Workspace from "./components/Workspace.jsx";
import NotFound from "./components/shell/NotFound.jsx";

export function appRoutes({ store, me, onSignedOut }) {
  return (
    <Route element={<AppShell />}>
      <Route index element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsDashboard store={store} me={me} onSignedOut={onSignedOut} />} />
      <Route path="/projects/new" element={<NewProject store={store} />} />
      <Route path="/projects/:projectId" element={<ProjectOverview store={store} me={me} />} />
      <Route
        path="/projects/:projectId/takeoff"
        element={<Workspace store={store} me={me} onSignedOut={onSignedOut} />}
      />
      <Route path="*" element={<NotFound />} />
    </Route>
  );
}
