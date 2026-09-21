import { useCallback, useState } from "react";

/* ============================================================
   useSaveFeedback.js — the two generic feedback surfaces CLAUDE.md's
   "No save buttons" rule asks every screen to show: a Saving…/Saved
   indicator in the top bar, and a self-dismissing toast per action.

   Pulled out of useReviewStore.js (task-4 review, "duplicated logic,
   not components") once ProjectSettings.jsx needed the identical
   behaviour without the store subscription/poll machinery the rest of
   that hook carries -- this file holds only the save-state and toast
   state machines, with no `store`, no snapshot, no poll. useReviewStore
   uses this for its own `saved`/`toast`/`showToast`/`dismissToast`/
   `runMutation`, unchanged in behaviour and public shape; every screen
   that already consumes those five off useReviewStore or
   useWorkspaceContext keeps working exactly as before.
   ============================================================ */

// How long a toast stays up before it self-dismisses.
const TOAST_MS = 5000;
// How long "Couldn't save — retrying" shows before falling back to
// "Saved" -- an actual technical failure gets this recovery window;
// a stale-version refusal (see runMutation below) never reaches it.
const ERROR_RECOVERY_MS = 2600;

const uid = (p) => p + "_" + Math.random().toString(36).slice(2, 9);

export function useSaveFeedback({ initialSaved = null } = {}) {
  const [saved, setSaved] = useState(initialSaved);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((text) => {
    const id = uid("t");
    setToast({ id, text });
    setTimeout(() => setToast((t) => (t && t.id === id ? null : t)), TOAST_MS);
  }, []);

  const dismissToast = useCallback(() => setToast(null), []);

  // Autosave status (DESIGN.md): Saving… while the request is in
  // flight, Saved <time> once it lands. A stale-version refusal is not
  // a save failure — nothing was lost, the write was correctly refused
  // — so it resolves straight back to "saved" rather than the retrying
  // copy, which is reserved for an actual technical failure. That one
  // error code is a generic optimistic-concurrency convention (task-13b),
  // not a review-store or polling concern, so it stays here rather than
  // being re-decided by every caller.
  const runMutation = useCallback(async (fn) => {
    setSaved({ state: "saving", at: Date.now() });
    try {
      const result = await fn();
      setSaved({ state: "saved", at: Date.now() });
      return result;
    } catch (err) {
      if (err?.code === "stale_item_version") {
        setSaved({ state: "saved", at: Date.now() });
      } else {
        setSaved({ state: "error", at: Date.now() });
        setTimeout(() => setSaved((s) => (s.state === "error" ? { state: "saved", at: Date.now() } : s)), ERROR_RECOVERY_MS);
      }
      throw err;
    }
  }, []);

  return { saved, toast, showToast, dismissToast, runMutation };
}
