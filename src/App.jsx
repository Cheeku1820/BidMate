import { useEffect, useState } from "react";
import { createStore } from "./lib/store/index.js";
import Login from "./components/Login.jsx";
import Workspace from "./components/Workspace.jsx";

/* ============================================================
   App.jsx — composition and routing between login and workspace, and
   nothing else (task-16-brief.md §1's suggested split). The store is
   created once, outside React state, since neither implementation's
   identity should change across renders. me() is the one call this
   file makes directly: the seed store's always resolves; the api
   store's rejects with `not_signed_in` when there is no session
   cookie, which is the entire login gate — Login.jsx is never rendered
   in seed mode for exactly that reason.
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

  if (!me) {
    return <Login onSignedIn={setMe} />;
  }

  return <Workspace store={store} me={me} onSignedOut={() => setMe(null)} />;
}
