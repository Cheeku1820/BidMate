/* ============================================================
   ProjectNav.jsx — spec §4.2's workspace navigation.

   All thirteen workspaces are listed because spec §4.2 requires the
   current stage, completed stages, and unresolved blockers to stay
   visible -- hiding the ones that are not built yet would hide the shape
   of the workflow. Unbuilt workspaces render as disabled with a reason
   rather than as links to an empty page.

   Accessible-name fix, applied identically here and in CompanyNav.jsx so
   the two navs never drift: `aria-label` on a bare `<span>` with no ARIA
   role is commonly dropped by assistive technology, since a span has no
   implicit role for the label to attach to. `role="link"` gives the
   label something to attach to, and `aria-disabled="true"` plus
   `tabIndex={-1}` keep it out of the tab order and read as unavailable
   rather than actionable.

   `aria-label` is set explicitly rather than relying on "name from
   content" -- with thirteen items sharing one `title`, a browser that
   favors `title` in its accessible-name computation (observed in
   manual verification) would announce every disabled workspace as the
   same generic phrase, losing which workspace is which. The explicit
   per-item label keeps that distinction no matter which the browser
   prefers.
   ============================================================ */

import { NavLink } from "react-router-dom";

const WORKSPACES = [
  { slug: "", label: "Overview", built: true },
  { slug: "documents", label: "Documents", built: true },
  { slug: "notes", label: "Notes & assumptions", built: false },
  { slug: "takeoff", label: "Blueprint takeoff", built: true },
  { slug: "spreadsheet", label: "Takeoff spreadsheet", built: true },
  { slug: "assemblies", label: "Assemblies", built: false },
  { slug: "labor", label: "Labor", built: false },
  { slug: "pricing", label: "Material pricing", built: false },
  { slug: "estimate", label: "Estimate summary", built: false },
  { slug: "revisions", label: "Revisions", built: false },
  { slug: "final-review", label: "Final review", built: false },
  { slug: "export", label: "Export", built: true },
  { slug: "settings", label: "Project settings", built: true },
];

export default function ProjectNav({ projectId }) {
  return (
    <nav className="project-nav" aria-label="Project workspaces">
      <ul className="project-nav-list">
        {WORKSPACES.map(({ slug, label, built }) => {
          const to = slug ? `/projects/${projectId}/${slug}` : `/projects/${projectId}`;
          if (!built) {
            return (
              <li key={label}>
                <span
                  className="project-nav-link is-unavailable"
                  role="link"
                  aria-disabled="true"
                  tabIndex={-1}
                  aria-label={`${label} — not built yet`}
                  title={`${label} isn't built yet.`}
                >
                  {label}
                </span>
              </li>
            );
          }
          return (
            <li key={label}>
              <NavLink
                end={slug === ""}
                to={to}
                className={({ isActive }) => (isActive ? "project-nav-link is-active" : "project-nav-link")}
              >
                {label}
              </NavLink>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
