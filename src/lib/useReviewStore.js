import { useCallback, useEffect, useRef, useState } from "react";
import { PRESENCE_BEAT_MS } from "./store/api.js";

/* ============================================================
   useReviewStore.js — the snapshot hook (task-16-brief.md's suggested
   split): store subscription, poll lifecycle, presence beat, save
   state, and every mutation wrapper. This is what replaced sync.js's
   direct read/write/subscribe calls and App.jsx's old commit()
   function — mutations now call a store method and re-render from the
   response, per the design doc's "writes are not optimistic."

   One state slot, `itemError`, covers both kinds of single-item
   mutation refusal a real backend can return: a stale write
   (`stale_item_version`, task-13b) and an ordinary domain refusal
   (`missing_information_blocks_approval`, say). Both get the same
   inline treatment — DESIGN.md's rule that error copy sits adjacent to
   the affected thing, not in a dialog the estimator meets away from the
   evidence — so this hook does not need two parallel mechanisms for
   what is, from the estimator's chair, the same situation: "your last
   action didn't take effect, and here's why." The stale case gets one
   extra affordance (a "refresh" action layered on by the caller,
   ItemDetailPanel), never a silent retry of the estimator's own write
   on top of whatever changed (task-16-brief.md §4).
   ============================================================ */

const uid = (p) => p + "_" + Math.random().toString(36).slice(2, 9);

export function useReviewStore(store, { onSignedOut } = {}) {
  const [snapshot, setSnapshot] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [saved, setSaved] = useState({ state: "saved", at: Date.now() });
  const [toast, setToast] = useState(null);
  const [itemError, setItemError] = useState(null);
  const presenceRef = useRef({ sheetId: null, itemId: null });

  const handleSignedOut = useCallback(
    (err) => {
      if (err?.code === "not_signed_in") {
        onSignedOut?.();
        return true;
      }
      return false;
    },
    [onSignedOut]
  );

  const refresh = useCallback(async () => {
    try {
      const snap = await store.getSnapshot();
      setSnapshot(snap);
      setLoadError(null);
    } catch (err) {
      if (handleSignedOut(err)) return;
      setLoadError(err?.message || "Couldn't load this project. Check your connection and try again.");
    }
  }, [store, handleSignedOut]);

  // Store subscription + poll lifecycle. subscribe()'s cadence is a
  // per-store decision (seed.js reacts to real BroadcastChannel/storage
  // events; api.js runs its own three-second poll internally) — this
  // hook is deliberately ignorant of which, and does not layer a
  // second interval on top.
  useEffect(() => {
    let cancelled = false;
    refresh();
    const unsubscribe = store.subscribe(() => {
      if (!cancelled) refresh();
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [store, refresh]);

  // The presence beat, shared by both stores (task-16-brief.md carry-
  // forward 10 pins api.js's PRESENCE_BEAT_MS to under the server's
  // documented 10s heartbeat assumption; this is the one place that
  // constant gets scheduled).
  useEffect(() => {
    const beat = () => store.setPresence(presenceRef.current).catch(() => {});
    beat();
    const iv = setInterval(beat, PRESENCE_BEAT_MS);
    return () => clearInterval(iv);
  }, [store]);

  const setPresenceTarget = useCallback(
    (sheetId, itemId) => {
      presenceRef.current = { sheetId: sheetId ?? null, itemId: itemId ?? null };
      store.setPresence(presenceRef.current).catch(() => {});
    },
    [store]
  );

  const showToast = useCallback((text) => {
    const id = uid("t");
    setToast({ id, text });
    setTimeout(() => setToast((t) => (t && t.id === id ? null : t)), 5000);
  }, []);

  const dismissToast = useCallback(() => setToast(null), []);
  const clearItemError = useCallback(() => setItemError(null), []);

  // Autosave status (DESIGN.md): Saving… while the request is in
  // flight, Saved <time> once it lands. A stale-version refusal is not
  // a save failure — nothing was lost, the write was correctly refused
  // — so it resolves straight back to "saved" rather than the retrying
  // copy, which is reserved for an actual technical failure.
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
        setTimeout(() => setSaved((s) => (s.state === "error" ? { state: "saved", at: Date.now() } : s)), 2600);
      }
      throw err;
    }
  }, []);

  function patchItem(item, version) {
    setSnapshot((snap) => (snap ? { ...snap, version, items: snap.items.map((i) => (i.id === item.id ? item : i)) } : snap));
  }

  function removeItemLocal(id, version) {
    setSnapshot((snap) => (snap ? { ...snap, version, items: snap.items.filter((i) => i.id !== id) } : snap));
  }

  // Shared tail for the five single-item mutations: run it, patch (or
  // remove) the one item the response describes, toast the label, and
  // clear any earlier refusal banner for this item — or, on refusal,
  // leave state untouched and surface it as `itemError` rather than an
  // unhandled rejection, so a caller never needs its own try/catch to
  // stay on-screen after a refusal.
  //
  // The response only describes the one item it touched — totals and
  // the undo head moved too (an approval changes approvedUnits; any
  // mutation changes the undo head) but this module has no way to
  // recompute either without duplicating a server-only computation
  // (invariant 1: totals are computed in exactly one place). Patching
  // the item first keeps the field the estimator just changed correct
  // with zero latency; the refresh() right after corrects everything
  // else within the same tick rather than waiting for the next poll —
  // for the seed store there IS no periodic poll to wait for at all
  // (its subscribe() only fires on another tab's broadcast), so without
  // this the drawer would show stale totals indefinitely after a
  // single-tab mutation.
  const runItemMutation = useCallback(
    async (id, fn, { removes = false } = {}) => {
      try {
        const res = await runMutation(fn);
        if (removes) removeItemLocal(id, res.version);
        else patchItem(res.item, res.version);
        showToast(res.label);
        setItemError(null);
        await refresh();
        return res;
      } catch (err) {
        if (handleSignedOut(err)) return null;
        setItemError({ itemId: id, code: err?.code ?? "request_failed", message: err?.message || "This action could not be completed." });
        return null;
      }
    },
    [runMutation, showToast, handleSignedOut, refresh]
  );

  const approveItem = useCallback((id, version) => runItemMutation(id, () => store.approveItem(id, version)), [store, runItemMutation]);
  const rejectItem = useCallback((id, version) => runItemMutation(id, () => store.rejectItem(id, version)), [store, runItemMutation]);
  const unrejectItem = useCallback((id, version) => runItemMutation(id, () => store.unrejectItem(id, version)), [store, runItemMutation]);
  const editItem = useCallback((id, changes, version) => runItemMutation(id, () => store.editItem(id, changes, version)), [store, runItemMutation]);
  const deleteItem = useCallback((id, version) => runItemMutation(id, () => store.deleteItem(id, version), { removes: true }), [store, runItemMutation]);

  // The three compound actions each return a full, authoritative
  // snapshot rather than one item — the whole point of a scale
  // confirmation or an undo/redo is that more than one row can move at
  // once (DESIGN.md, "Undo semantics" — one undo reverses a whole scale
  // confirmation, not fourteen).
  const setScale = useCallback(
    async (sheetId, value) => {
      try {
        const res = await runMutation(() => store.setScale(sheetId, value));
        setSnapshot(res.snapshot);
        showToast(res.label);
        return res;
      } catch (err) {
        handleSignedOut(err);
        throw err;
      }
    },
    [store, runMutation, showToast, handleSignedOut]
  );

  const undo = useCallback(async () => {
    try {
      const res = await runMutation(() => store.undo());
      if (res.performed) {
        setSnapshot(res.snapshot);
        showToast(res.label);
        setItemError(null);
      }
      return res;
    } catch (err) {
      handleSignedOut(err);
      throw err;
    }
  }, [store, runMutation, showToast, handleSignedOut]);

  const redo = useCallback(async () => {
    try {
      const res = await runMutation(() => store.redo());
      if (res.performed) {
        setSnapshot(res.snapshot);
        showToast(res.label);
        setItemError(null);
      }
      return res;
    } catch (err) {
      handleSignedOut(err);
      throw err;
    }
  }, [store, runMutation, showToast, handleSignedOut]);

  return {
    snapshot,
    loading: snapshot === null && !loadError,
    loadError,
    saved,
    toast,
    dismissToast,
    itemError,
    clearItemError,
    setPresenceTarget,
    refresh,
    approveItem,
    rejectItem,
    unrejectItem,
    editItem,
    deleteItem,
    setScale,
    undo,
    redo,
  };
}
