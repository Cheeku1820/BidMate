/* ============================================================
   screenContext.jsx — how the conversation panel knows what is on
   screen.

   The panel mounts in AppShell, above ProjectWorkspaceLayout, so it
   cannot read the layout's selection or a screen's filter through
   props. This context carries them up: the layout reports the selection
   (with labels, so the panel's header can name a sheet without holding
   the snapshot), the two screens with filters report a view, and the
   screen name comes from the path through one table that mirrors
   routes.jsx.

   SCREEN_NAMES is mirrored verbatim by api/app/assistant/schemas.py.
   Adding a screen is one row here and one there; the server never
   parses a URL.
   ============================================================ */

import { createContext, useContext, useEffect, useMemo, useState } from "react";

export const SCREEN_NAMES = [
  "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
  "notes", "labor", "pricing", "export", "settings",
];

export const SCREEN_LABELS = {
  overview: "Project overview",
  documents: "Documents",
  confirm: "Confirm drawings",
  processing: "Processing",
  takeoff: "Blueprint",
  spreadsheet: "Spreadsheet",
  notes: "Notes and assumptions",
  labor: "Labor",
  pricing: "Material pricing",
  export: "Export",
  settings: "Project settings",
};

// The suffix after /projects/:id, or "" for the overview. Same exclusion
// of "new" as AppShell.PROJECT_ROUTE: /projects/new belongs to no project.
const PROJECT_PATH = /^\/projects\/(?!new(?:\/|$))[^/]+(?:\/(.*))?$/;
const BY_SUFFIX = {
  "": "overview",
  documents: "documents",
  "documents/confirm": "confirm",
  processing: "processing",
  takeoff: "takeoff",
  spreadsheet: "spreadsheet",
  notes: "notes",
  labor: "labor",
  pricing: "pricing",
  export: "export",
  settings: "settings",
};

export function screenNameFromPath(pathname) {
  const match = PROJECT_PATH.exec(pathname);
  if (!match) return null;
  const suffix = (match[1] ?? "").replace(/\/+$/, "");
  return BY_SUFFIX[suffix] ?? null;
}

const noop = () => {};
const DEFAULT = { selection: {}, view: {}, panelOpen: false, setSelection: noop, setView: noop, setPanelOpen: noop };

export const ConversationScreenContext = createContext(DEFAULT);

export function ConversationScreenProvider({ children, panelOpen = false, setPanelOpen = noop }) {
  const [selection, setSelection] = useState({});
  const [view, setView] = useState({});
  const value = useMemo(
    () => ({ selection, view, panelOpen, setSelection, setView, setPanelOpen }),
    [selection, view, panelOpen, setPanelOpen],
  );
  return <ConversationScreenContext.Provider value={value}>{children}</ConversationScreenContext.Provider>;
}

export function useConversationScreenContext() {
  return useContext(ConversationScreenContext);
}

/* Called once by ProjectWorkspaceLayout. Labels ride along so the
   panel's header can say "E2.1 · 20A duplex receptacle selected"
   without a second snapshot subscription. */
export function useConversationSelection({ sheetId = null, sheetLabel = null, itemId = null, itemLabel = null }) {
  const { setSelection } = useConversationScreenContext();
  useEffect(() => {
    setSelection({ sheetId, sheetLabel, itemId, itemLabel });
    return () => setSelection({});
  }, [setSelection, sheetId, sheetLabel, itemId, itemLabel]);
}

/* Called by a screen that has a status filter or a search box. `filter`
   is one of the four review keys (ready / attention / missing /
   approved) or null; `search` is the text in the box. */
export function useConversationView({ filter = null, search = "" }) {
  const { setView } = useConversationScreenContext();
  useEffect(() => {
    setView({ filter, search });
    return () => setView({});
  }, [setView, filter, search]);
}
