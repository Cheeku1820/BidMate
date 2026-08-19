import { useEffect, useState } from "react";
import { BrowserRouter, Routes } from "react-router-dom";
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

  return (
    <BrowserRouter>
      <Routes>{appRoutes({ store, me, onSignedOut: () => setMe(null) })}</Routes>
    </BrowserRouter>
  );
}
