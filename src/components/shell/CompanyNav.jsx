/* ============================================================
   CompanyNav.jsx — spec §4.1's persistent left navigation.

   Text labels alongside icons, never icon-only by default: spec §4.1
   forbids hiding essential destinations behind icons, and CLAUDE.md's
   users are described as often uncomfortable with unfamiliar software.
   Collapsing to icons-only is an explicit, reversible user action (or
   the takeoff route's own default — see below), not the resting state,
   and every collapsed icon still carries an aria-label and a title so
   the label survives for screen readers and on hover.

   Each destination declares whether it is routed (`available` in
   DESTINATIONS below), and today three are not: the company library,
   integrations, and help are spec §4.1 destinations that are not built
   yet. They stay visible — the product's shape should stay legible —
   but render as non-interactive with a reason, rather than as a link
   that 404s into copy about an out-of-date link or an archived project,
   which would be actively misleading for a destination that was simply
   never built.

   Accessible-name fix, applied identically here and in ProjectNav.jsx so
   the two navs never drift: `aria-label` on a bare `<span>` with no ARIA
   role is commonly dropped by assistive technology, because a span has
   no implicit role for the label to attach to -- when the nav is
   collapsed these items announced as nothing at all. `role="link"` gives
   the label somewhere to attach; `aria-disabled="true"` plus
   `tabIndex={-1}` keep it out of the tab order and read as unavailable
   rather than actionable.
   ============================================================ */

import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BookOpen, HelpCircle, LayoutGrid, PanelLeftClose, PanelLeftOpen, Plug, Settings, Target, Zap } from "lucide-react";

const DESTINATIONS = [
  { to: "/projects", label: "Projects", Icon: LayoutGrid, available: true },
  { to: "/estimate", label: "Instant estimate", Icon: Zap, available: true },
  { to: "/accuracy", label: "Accuracy", Icon: Target, available: true },
  { to: "/library", label: "Company library", Icon: BookOpen, available: false },
  { to: "/integrations", label: "Integrations", Icon: Plug, available: false },
  { to: "/settings", label: "Company settings", Icon: Settings, available: true },
  { to: "/help", label: "Help", Icon: HelpCircle, available: false },
];

// Matches /projects/:anything/takeoff — the one screen whose acceptance
// criterion (spec §12: the blueprint stays the largest element) this
// nav's fixed width would otherwise threaten at the 1024px floor the
// README claims support for. See styles.css's "Application shell"
// section for the width math.
const TAKEOFF_ROUTE = /^\/projects\/[^/]+\/takeoff(\/|$)/;

export default function CompanyNav() {
  const location = useLocation();
  const isTakeoffRoute = TAKEOFF_ROUTE.test(location.pathname);
  const [collapsed, setCollapsed] = useState(isTakeoffRoute);

  // AppShell (and CompanyNav within it) is a layout route that stays
  // mounted across in-app navigation — only <Outlet /> swaps. Re-deriving
  // the default whenever the route crosses the takeoff boundary keeps
  // "collapsed by default on the takeoff route" true after client-side
  // navigation, not only on a fresh page load, without tracking a
  // separate "did the user override this" flag — a smaller rule than
  // that would need, and proportionate to what this fix asks for.
  useEffect(() => {
    setCollapsed(isTakeoffRoute);
  }, [isTakeoffRoute]);

  return (
    <nav className={collapsed ? "company-nav is-collapsed" : "company-nav"} aria-label="Main">
      <div className="company-nav-head">
        {!collapsed && <div className="company-nav-brand">BidMate</div>}
        <button
          type="button"
          className="company-nav-toggle"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
          title={collapsed ? "Expand navigation" : "Collapse navigation"}
        >
          {collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}
        </button>
      </div>
      <ul className="company-nav-list">
        {DESTINATIONS.map(({ to, label, Icon, available }) =>
          available ? (
            <li key={to}>
              <NavLink
                to={to}
                aria-label={label}
                title={label}
                className={({ isActive }) => (isActive ? "company-nav-link is-active" : "company-nav-link")}
              >
                <Icon size={18} aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </NavLink>
            </li>
          ) : (
            <li key={to}>
              <span
                className="company-nav-link is-unavailable"
                role="link"
                aria-disabled="true"
                tabIndex={-1}
                aria-label={`${label} — not built yet`}
                title={`${label} isn't built yet.`}
              >
                <Icon size={18} aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </span>
            </li>
          ),
        )}
      </ul>
    </nav>
  );
}
