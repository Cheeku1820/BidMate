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
  // "clean up" later. BrowserRouter matches window.location.pathname
  // verbatim, and every path in routes.jsx is absolute from "/", so any
  // deep link the server does not rewrite back to index.html falls to
  // the catch-all NotFound route. That is the everyday case here: the
  // Vite dev server and `npm run preview` serve the built files without
  // a history fallback, so reloading or opening /projects/<id>/review
  // directly would 404 the whole app. HashRouter routes on the URL
  // fragment instead ("/#/projects"), which the server never sees, so
  // deep links and reloads work with no rewrite rule and no basename.
  return (
    <HashRouter>
      <Routes>{appRoutes({ store, me, onSignedOut: () => setMe(null) })}</Routes>
    </HashRouter>
  );
}
