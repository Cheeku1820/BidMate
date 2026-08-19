import { useEffect, useState } from "react";
import { HashRouter, Routes } from "react-router-dom";
import { createStore } from "./lib/store/index.js";
import Login from "./components/Login.jsx";
import { appRoutes } from "./routes.jsx";

/* ============================================================
   App.jsx — the auth gate, and nothing else. Once a user is present it
   hands off to the route table in routes.jsx; before this task it handed
   off to a single workspace, which is the change that lets a second
   screen exist at all.
   ============================================================ */

const store = createStore();

export default function App() {
  const [me, setMe] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    store
      .me()
      .then((user) => {
        if (!cancelled) setMe(user);
      })
      .catch(() => {
        if (!cancelled) setMe(null);
      })
      .finally(() => {
        if (!cancelled) setChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!checked) return null;
  if (!me) return <Login onSignedIn={setMe} />;

  // HashRouter, not BrowserRouter — deliberately, not a preference to
  // "clean up" later. vite.config.js sets base: "./" because this app
  // ships two ways the README documents: .github/workflows/deploy.yml
  // publishes dist/ to GitHub Pages under a /takeoff-review/ subpath,
  // and demo/index.html is a committed single-file build meant to be
  // opened directly from disk (file://). BrowserRouter matches
  // window.location.pathname verbatim — on Pages that's
  // "/takeoff-review/", which matches none of routes.jsx's absolute
  // paths and falls straight to the catch-all NotFound route, making
  // the whole app unreachable; from file:// the pathname is a
  // filesystem path and <Link> navigation cannot work at all.
  // HashRouter routes on the URL fragment instead ("/#/projects"),
  // which is unaffected by either the serving subpath or the file://
  // origin, and needs no basename configuration to match.
  return (
    <HashRouter>
      <Routes>{appRoutes({ store, me, onSignedOut: () => setMe(null) })}</Routes>
    </HashRouter>
  );
}
