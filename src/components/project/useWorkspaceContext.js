/* ============================================================
   useWorkspaceContext.js — the accessor for what
   ProjectWorkspaceLayout provides.

   A thin wrapper over useOutletContext() rather than raw calls at each
   consumer: the error below is the reason. A component rendered outside
   the layout by mistake otherwise gets `undefined` and fails somewhere
   downstream with a destructuring error that says nothing about the
   actual cause.
   ============================================================ */

import { useOutletContext } from "react-router-dom";

export function useWorkspaceContext() {
  const context = useOutletContext();
  if (!context) {
    throw new Error(
      "useWorkspaceContext() was called outside ProjectWorkspaceLayout. " +
        "Project workspaces must be routed as children of the layout so they " +
        "share one store subscription and one selection.",
    );
  }
  return context;
}
