/* ============================================================
   useEstimate.js — the ROM estimate screen's one data hook.

   Follows useSchedule.js's shape: its own fetch, not the polled review
   snapshot. The reasoning is the same and a little stronger here — the
   ROM is a document an estimator opens, and the server recomputes the
   whole thing on every read (totals, the range, what scope removed), so
   there is nothing for this screen to keep in step.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { COPY } from "./estimateCopy.js";

export function useEstimate() {
  const { store, projectId, runMutation, showToast } = useWorkspaceContext();
  const [estimate, setEstimate] = useState(null); // null = loading
  const [loadError, setLoadError] = useState(null);

  const reload = useCallback(() => {
    setLoadError(null);
    return store
      .getEstimate(projectId)
      .then(setEstimate)
      .catch((err) => setLoadError(err?.message || COPY.loadError));
  }, [store, projectId]);

  useEffect(() => {
    reload();
  }, [reload]);

  /* An override routes through runMutation, so the top bar's
     Saving…/Saved and the five-second Undo toast behave exactly as they
     do for every other edit — the point of putting the write through
     commit() server-side was that nothing new had to be invented here
     either. The response is the whole document, so state is replaced
     rather than refetched. */

  const overrideLine = useCallback(
    async (line, value) => {
      try {
        const next = await runMutation(() =>
          store.overrideAssumption(line.id, { value, unit: line.unit }),
        );
        if (next && Array.isArray(next.sections)) setEstimate(next);
        showToast?.(`Entered ${line.title.toLowerCase()} as ${value}`);
        return true;
      } catch {
        return false;
      }
    },
    [store, runMutation, showToast],
  );

  return { estimate, loadError, reload, overrideLine };
}
