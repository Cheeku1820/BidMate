/* ============================================================
   CompanyNav.jsx — spec §4.1's persistent left navigation.

   Text labels alongside icons, never icon-only: spec §4.1 forbids
   hiding essential destinations behind icons, and CLAUDE.md's users are
   described as often uncomfortable with unfamiliar software. An
   unlabelled icon rail is exactly the kind of interface that costs them
   ten minutes and a phone call.
   ============================================================ */

import { NavLink } from "react-router-dom";
import { BookOpen, HelpCircle, LayoutGrid, Plug, Settings, Target } from "lucide-react";

const DESTINATIONS = [
  { to: "/projects", label: "Projects", Icon: LayoutGrid },
  { to: "/accuracy", label: "Accuracy", Icon: Target },
  { to: "/library", label: "Company library", Icon: BookOpen },
  { to: "/integrations", label: "Integrations", Icon: Plug },
  { to: "/settings", label: "Company settings", Icon: Settings },
  { to: "/help", label: "Help", Icon: HelpCircle },
];

export default function CompanyNav() {
  return (
    <nav className="company-nav" aria-label="Main">
      <div className="company-nav-brand">BidMate</div>
      <ul className="company-nav-list">
        {DESTINATIONS.map(({ to, label, Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) => (isActive ? "company-nav-link is-active" : "company-nav-link")}
            >
              <Icon size={18} aria-hidden="true" />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
