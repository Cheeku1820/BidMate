/* ============================================================
   AppTopBar.jsx — spec §4.3's persistent top bar.

   Company-level screens (projects dashboard, new project, project
   overview) render this for their title, save state, and primary
   action. The review workspace keeps its own TopBar.jsx unchanged in
   this task — it already carries save state, undo/redo, and presence
   for that one screen, and splitting those out is a larger refactor
   than this task's brief covers (task-6-brief.md's ambiguity
   resolution 3). This component exists so every *other* screen has
   somewhere to put the same save-state convention without duplicating
   TopBar.jsx's markup.

   `breadcrumb` is the way back out of a project. AppShell replaces the
   company nav with the project sidebar inside a project, so a project
   screen has no other route to company level; a screen that passes a
   breadcrumb gets the trail above a larger title, and one that doesn't
   renders exactly as it did before.
   ============================================================ */

import { Fragment } from "react";
import { Link } from "react-router-dom";

export default function AppTopBar({ title, subtitle, breadcrumb, saveState, children, primaryAction }) {
  const trail = breadcrumb?.filter(Boolean) ?? [];

  return (
    <header className={trail.length > 0 ? "app-top-bar app-top-bar--stacked" : "app-top-bar"}>
      <div className="app-top-bar-identity">
        {trail.length > 0 ? (
          // aria-hidden on the separators: "/" announced between every
          // crumb is noise, and <nav> plus the link text already convey
          // the structure.
          <nav className="app-top-bar-crumbs" aria-label="Breadcrumb">
            {trail.map((crumb, index) => (
              <Fragment key={crumb.to ?? crumb.label}>
                {index > 0 ? <span aria-hidden="true">/</span> : null}
                {crumb.to ? <Link to={crumb.to}>{crumb.label}</Link> : <span>{crumb.label}</span>}
              </Fragment>
            ))}
          </nav>
        ) : null}
        <span className="app-top-bar-title">{title}</span>
        {subtitle ? <span className="app-top-bar-subtitle">{subtitle}</span> : null}
      </div>
      <div className="app-top-bar-tools">
        {saveState ? (
          // .savestate (no hyphen) is the stylesheet's actual class,
          // shared with TopBar.jsx — .save-state doesn't exist in
          // styles.css and would render unstyled.
          <span className="savestate tabular" role="status" aria-live="polite">
            {saveState}
          </span>
        ) : null}
        {children}
        {primaryAction}
      </div>
    </header>
  );
}
