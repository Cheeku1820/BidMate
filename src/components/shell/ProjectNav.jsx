/* ============================================================
   ProjectNav.jsx — spec §4.2's workspace navigation, as the project's
   left sidebar.

   It used to be a horizontal tab strip that only four screens bothered
   to render. It is now the one rail an estimator navigates a project
   from, mounted by AppShell for every /projects/:id route, which is why
   no screen renders it itself any more.

   All thirteen workspaces are listed because spec §4.2 requires the
   current stage, completed stages, and unresolved blockers to stay
   visible -- hiding the ones that are not built yet would hide the shape
   of the workflow. Unbuilt workspaces render as disabled with a reason
   rather than as links to an empty page.

   Grouping. The thirteen are ordered exactly as before; the group
   headings are a reading aid over that order, not a reordering of it.
   They are sentence case rather than the small caps a nav of this shape
   usually uses, because spec §7 rules out all-caps headings and
   CLAUDE.md asks for sentence case throughout.

   What the badges may say. The project row carries `missingInfo` and
   `warningsOpen` -- item-level facts about the takeoff -- and nothing
   per-workspace beyond that. So those two counts appear on the two
   workspaces that are views of those items (DESIGN.md: the blueprint
   and the table are two views of one list, which is why the same number
   correctly appears on both) and nowhere else. No other workspace gets
   an invented count.

   Every badge pairs its hue with an icon and, through `aria-label`, the
   words -- never colour alone (CLAUDE.md). The same AlertCircle /
   AlertTriangle pair ProjectsDashboard.jsx uses, so "missing
   information" and "needs attention" look the same wherever an
   estimator meets them.

   Collapsed state. Mirrors CompanyNav.jsx, and for the same reason: on
   the takeoff route the blueprint has to stay the largest element on
   screen (spec §12) at the 1024px floor. Expanded is the designed state
   -- dot and label, no icons, per the layout this was built from -- so
   the per-workspace icons exist only to make the collapsed rail
   navigable, and appear only there.

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

import { Link, NavLink } from "react-router-dom";
import {
  AlertCircle,
  AlertTriangle,
  Boxes,
  Calculator,
  ClipboardCheck,
  DollarSign,
  Download,
  FileText,
  GitCompare,
  LayoutDashboard,
  Map,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  StickyNote,
  Table,
  Users,
} from "lucide-react";
import { bidDueChip } from "../../lib/format.js";
import { reviewProgress } from "../../lib/projectStage.js";

// Sentence case, spec §7's order, unchanged from the flat list this
// replaced. `counts` marks the workspaces the project row's warning
// numbers genuinely describe -- see the header comment.
const GROUPS = [
  {
    title: null,
    items: [{ slug: "", label: "Overview", built: true, Icon: LayoutDashboard }],
  },
  {
    title: "Evidence",
    items: [
      { slug: "documents", label: "Documents", built: true, Icon: FileText },
      { slug: "notes", label: "Notes & assumptions", built: true, Icon: StickyNote },
    ],
  },
  {
    title: "Takeoff",
    items: [
      { slug: "takeoff", label: "Blueprint takeoff", built: true, Icon: Map, counts: true },
      { slug: "spreadsheet", label: "Takeoff spreadsheet", built: true, Icon: Table, counts: true },
    ],
  },
  {
    title: "Cost",
    items: [
      { slug: "assemblies", label: "Assemblies", built: false, Icon: Boxes },
      { slug: "labor", label: "Labor", built: false, Icon: Users },
      { slug: "pricing", label: "Material pricing", built: false, Icon: DollarSign },
      { slug: "estimate", label: "Estimate summary", built: false, Icon: Calculator },
    ],
  },
  {
    title: "Close out",
    items: [
      { slug: "revisions", label: "Revisions", built: false, Icon: GitCompare },
      { slug: "final-review", label: "Final review", built: false, Icon: ClipboardCheck },
      { slug: "export", label: "Export", built: true, Icon: Download },
    ],
  },
  {
    title: "Project",
    items: [{ slug: "settings", label: "Project settings", built: true, Icon: Settings }],
  },
];

/** The two badges a workspace may carry, or an empty list. Returns the
 *  words as well as the hue so the caller never has to reconstruct them
 *  for `aria-label`. */
function badgesFor(item, project) {
  if (!item.counts || !project) return [];
  const out = [];
  const missing = project.missingInfo ?? 0;
  const attention = project.warningsOpen ?? 0;
  if (missing > 0) {
    out.push({
      key: "missing",
      count: missing,
      Icon: AlertCircle,
      text: `${missing} ${missing === 1 ? "item is" : "items are"} missing required information`,
    });
  }
  if (attention > 0) {
    out.push({
      key: "attention",
      count: attention,
      Icon: AlertTriangle,
      text: `${attention} ${attention === 1 ? "item needs" : "items need"} attention`,
    });
  }
  return out;
}

function WorkspaceBadges({ badges, collapsed }) {
  if (badges.length === 0) return null;

  // Collapsed, the row is 31px of usable width and already holds the
  // workspace icon; two chips do not fit and overflowed it. One pip
  // marks the more serious of the two states -- missing information
  // outranks needs attention, because it is the one with no override --
  // and its label still names both, so nothing is lost to anyone reading
  // by ear. The numbers come back with the labels when the rail expands.
  if (collapsed) {
    const worst = badges[0];
    const text = badges.map((b) => b.text).join("; ");
    return <span className={`ws-pip ws-pip--${worst.key}`} role="img" aria-label={text} title={text} />;
  }

  return (
    <span className="ws-badges">
      {badges.map(({ key, count, Icon, text }) => (
        <span key={key} className={`ws-badge ws-badge--${key} tabular`} role="img" aria-label={text} title={text}>
          <Icon size={12} aria-hidden="true" />
          {count}
        </span>
      ))}
    </span>
  );
}

/** The project card at the top of the rail: who the job is for, how
 *  close the bid is, and how much of the review is done. Every value is
 *  read off the project row -- a project that has none of them (a
 *  freshly created one) simply shows fewer lines rather than
 *  placeholders. */
function ProjectCard({ project }) {
  const progress = reviewProgress(project);
  const due = bidDueChip(project.bidDueDate);
  const subtitleParts = [project.number ? `#${project.number}` : null, project.customer].filter(Boolean);

  return (
    <div className="project-card">
      <p className="project-card-name">{project.name}</p>
      {subtitleParts.length > 0 ? (
        <p className="project-card-sub tabular">{subtitleParts.join(" · ")}</p>
      ) : null}

      <div className="project-card-chips">
        {due ? <span className={`due-chip due-chip--${due.tone}`}>{due.label}</span> : null}
        <span className="project-card-rev">{project.revisionSetLabel || "No drawing set yet"}</span>
      </div>

      {progress.total > 0 ? (
        <>
          {/* Not a <progress> element: this is a decorative echo of the
              sentence beneath it, which already states the same fact in
              words and numbers. Marking it up as a second progressbar
              would make assistive technology announce the figure twice. */}
          <div className="project-card-meter" aria-hidden="true">
            <span style={{ width: `${progress.percent}%` }} />
          </div>
          <p className="project-card-progress tabular">
            {progress.approved} of {progress.total} items approved
          </p>
        </>
      ) : (
        <p className="project-card-progress">No takeoff yet</p>
      )}
    </div>
  );
}

export default function ProjectNav({
  projectId,
  project = null,
  companyName = null,
  collapsed = false,
  onToggleCollapsed = null,
}) {
  return (
    // The rail is a <div>; only the workspace list is the <nav>. The
    // brand link and the project card are not workspaces, and having
    // them inside the labelled nav made "Project workspaces" announce
    // fourteen destinations for thirteen workspaces.
    <div className={collapsed ? "project-sidebar is-collapsed" : "project-sidebar"}>
      <div className="project-sidebar-head">
        {!collapsed && (
          <Link className="project-sidebar-brand" to="/projects">
            <span className="project-sidebar-brand-mark" aria-hidden="true" />
            <span>
              <span className="project-sidebar-brand-name">BidMate</span>
              {companyName ? <span className="project-sidebar-brand-org">{companyName}</span> : null}
            </span>
          </Link>
        )}
        {onToggleCollapsed ? (
          <button
            type="button"
            className="company-nav-toggle"
            onClick={onToggleCollapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
          >
            {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
          </button>
        ) : null}
      </div>

      {!collapsed && project ? <ProjectCard project={project} /> : null}

      <nav className="project-sidebar-scroll" aria-label="Project workspaces">
        {GROUPS.map((group, groupIndex) => {
          const headingId = group.title ? `ws-group-${groupIndex}` : undefined;
          return (
            <div className="project-sidebar-group" key={group.title ?? "primary"}>
              {group.title && !collapsed ? (
                <h2 className="project-sidebar-group-title" id={headingId}>
                  {group.title}
                </h2>
              ) : null}
              <ul className="project-sidebar-list" aria-labelledby={collapsed ? undefined : headingId}>
                {group.items.map(({ slug, label, built, Icon, counts }) => {
                  const to = slug ? `/projects/${projectId}/${slug}` : `/projects/${projectId}`;
                  const badges = badgesFor({ counts }, project);

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
                          {collapsed ? (
                            <Icon size={18} aria-hidden="true" />
                          ) : (
                            <>
                              <span className="ws-dot ws-dot--unavailable" aria-hidden="true" />
                              <span className="ws-label">{label}</span>
                            </>
                          )}
                        </span>
                      </li>
                    );
                  }

                  return (
                    <li key={label}>
                      <NavLink
                        end={slug === ""}
                        to={to}
                        aria-label={label}
                        title={label}
                        className={({ isActive }) => (isActive ? "project-nav-link is-active" : "project-nav-link")}
                      >
                        {collapsed ? (
                          <Icon size={18} aria-hidden="true" />
                        ) : (
                          <>
                            <span className="ws-dot" aria-hidden="true" />
                            <span className="ws-label">{label}</span>
                          </>
                        )}
                        <WorkspaceBadges badges={badges} collapsed={collapsed} />
                      </NavLink>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>
    </div>
  );
}
