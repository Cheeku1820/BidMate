/* ============================================================
   AppShell.jsx — the frame every signed-in screen renders inside.

   Holds the company navigation and the outlet. It deliberately does not
   own the top bar: a company-level screen and a project workspace put
   different things in it, so each route renders its own AppTopBar rather
   than the shell guessing.
   ============================================================ */

import { Outlet } from "react-router-dom";
import CompanyNav from "./CompanyNav.jsx";

export default function AppShell() {
  return (
    <div className="app-shell">
      <CompanyNav />
      <main className="app-shell-main">
        <Outlet />
      </main>
    </div>
  );
}
