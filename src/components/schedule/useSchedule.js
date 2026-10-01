/* ============================================================
   useSchedule.js — the schedule screen's one data hook.

   The schedule is not part of the polled review snapshot: a phase or a
   crew edit never changes the takeoff, so this screen fetches its own
   state, the way Labor and Material pricing fetch theirs. Every write
   answers with the whole schedule (a crew moves every later bar), so a
   mutation replaces state from the response rather than refetching.

   What it borrows from the review store is the reporting: runMutation
   drives the top bar's Saving…/Saved, showToast the five-second Undo.
   Undo pulls from the shared stack and lands in the action log, not in
   this screen's state, so the toast's Undo reloads.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { COPY } from "./scheduleCopy.js";

export function useSchedule() {
  const { store, projectId, runMutation, showToast, refresh } = useWorkspaceContext();
  const [schedule, setSchedule] = useState(null); // null = loading
  const [loadError, setLoadError] = useState(null);
  const [saveError, setSaveError] = useState(null);

  const reload = useCallback(() => {
    setLoadError(null);
    return store
      .getSchedule(projectId)
      .then(setSchedule)
      .catch((err) => setLoadError(err?.message || COPY.loadError));
  }, [store, projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const mutate = useCallback(
    async (fn, label) => {
      setSaveError(null);
      try {
        const next = await runMutation(fn);
        // Guarded rather than assumed: setItemPhase answers with an
        // item, not a schedule, and a reload follows it instead.
        if (next && Array.isArray(next.phases)) setSchedule(next);
        // The phase list every other screen reads rides the snapshot,
        // so refreshing it here is what makes the item panel's field
        // and the spreadsheet's column appear the moment a second
        // phase exists -- rather than on the next poll a few seconds
        // later, or a reload.
        await refresh?.();
        if (label) showToast(label);
        return next;
      } catch (err) {
        setSaveError(err?.message || COPY.saveError);
        return null;
      }
    },
    [runMutation, showToast, refresh],
  );

  return { schedule, loadError, saveError, reload, mutate };
}
