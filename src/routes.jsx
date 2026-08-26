/* ============================================================
   routes.jsx — one place that knows what URLs exist.

   Adding a workspace is a row here plus a component, not a change in
   four files. Screens that spec §1 lists but that are not routed here
   yet (accuracy, company library, integrations, company settings, help)
   still appear in CompanyNav.jsx — spec §4.1 wants the product's full
   shape legible even before every screen is built — but render there as
   disabled with a reason rather than getting a route that would only
   land on NotFound. A route table entry pointing at nothing is worse
   than a nav item that says plainly it isn't built yet, and spec §20
   requires error copy to name a recovery action, which "not built yet"
   is not one of.
   ============================================================ */

import { Navigate, Route } from "react-router-dom";
import AppShell from "./components/shell/AppShell.jsx";
import ProjectsDashboard from "./components/projects/ProjectsDashboard.jsx";
import NewProject from "./components/projects/NewProject.jsx";
import ProjectOverview from "./components/projects/ProjectOverview.jsx";
import UploadDocuments from "./components/documents/UploadDocuments.jsx";
import ConfirmDrawings from "./components/documents/ConfirmDrawings.jsx";
import ProcessingStatus from "./components/documents/ProcessingStatus.jsx";
import ProjectWorkspaceLayout from "./components/project/ProjectWorkspaceLayout.jsx";
import Workspace from "./components/Workspace.jsx";
import TakeoffSpreadsheet from "./components/takeoff/TakeoffSpreadsheet.jsx";
import ExportPreview from "./components/export/ExportPreview.jsx";
import CompanySettings from "./components/settings/CompanySettings.jsx";
import ProjectSettings from "./components/settings/ProjectSettings.jsx";
import Accuracy from "./components/accuracy/Accuracy.jsx";
import EstimateDemo from "./components/estimate/EstimateDemo.jsx";
import NotFound from "./components/shell/NotFound.jsx";

export function appRoutes({ store, me, onSignedOut }) {
  return (
    <Route element={<AppShell />}>
      <Route index element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsDashboard store={store} me={me} onSignedOut={onSignedOut} />} />
      <Route path="/accuracy" element={<Accuracy />} />
      <Route path="/estimate" element={<EstimateDemo />} />
      <Route path="/settings" element={<CompanySettings />} />
      <Route path="/projects/new" element={<NewProject store={store} />} />
      <Route path="/projects/:projectId" element={<ProjectOverview store={store} me={me} />} />
      <Route path="/projects/:projectId/settings" element={<ProjectSettings store={store} />} />
      <Route path="/projects/:projectId/documents" element={<UploadDocuments />} />
      <Route path="/projects/:projectId/documents/confirm" element={<ConfirmDrawings />} />
      <Route path="/projects/:projectId/processing" element={<ProcessingStatus store={store} />} />
      <Route
        path="/projects/:projectId"
        element={<ProjectWorkspaceLayout store={store} me={me} onSignedOut={onSignedOut} />}
      >
        <Route path="takeoff" element={<Workspace />} />
        <Route path="spreadsheet" element={<TakeoffSpreadsheet />} />
        <Route path="export" element={<ExportPreview />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Route>
  );
}
