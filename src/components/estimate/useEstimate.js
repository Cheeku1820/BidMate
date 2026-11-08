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
  const { store, projectId } = useWorkspaceContext();
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

  return { estimate, loadError, reload };
}
