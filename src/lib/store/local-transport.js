/* ============================================================
   local-transport.js — the honest replacement for sync.js.

   Storage guards, identity, and presence: the local multi-tab
   transport (localStorage as the database, BroadcastChannel as the
   realtime layer — ROADMAP.md, "What the prototype maps to"). This is
   a different concern from "the seed fixture" (seed-fixture.js) or
   "the store's mutation rules" (seed.js and friends), which is why it
   is its own file rather than folded into either.

   Copied (not imported) from sync.js's own internals, per
   task-15-brief.md: "Move the localStorage, BroadcastChannel, and
   identity() internals from sync.js into this module." A distinct
   namespace (NS below) keeps this store's data from ever colliding
   with sync.js's, since App.jsx still reads/writes sync.js's keys
   until Task 16 switches it over.
   ============================================================ */

const NS = "takeoff-review:store:";

/* jsdom's BroadcastChannel support varies by version and Node's global may
   not survive into it — guarded the same way sync.js guards it, rather than
   assumed present. Missing it just means this store works single-tab. */
let channel = null;
try {
  channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(NS + "bus") : null;
} catch {
  channel = null;
}

/* Sandboxed frames block localStorage; fall back to an in-memory map so a
   single tab still works end to end, matching sync.js's own fallback. */
const memory = new Map();
const backing = (() => {
  try {
    const probe = "__probe__";
    localStorage.setItem(probe, "1");
    localStorage.removeItem(probe);
    return localStorage;
  } catch {
    return {
      getItem: (k) => (memory.has(k) ? memory.get(k) : null),
      setItem: (k, v) => memory.set(k, v),
      removeItem: (k) => memory.delete(k),
    };
  }
})();

export function storageRead(key, fallback) {
  try {
    const raw = backing.getItem(NS + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function storageWrite(key, value) {
  try {
    backing.setItem(NS + key, JSON.stringify(value));
    channel?.postMessage({ key, at: Date.now() });
    return true;
  } catch {
    return false;
  }
}

export function storageSubscribe(handler) {
  const onBus = (e) => handler(e.data?.key);
  const onStorage = (e) => {
    if (e.key && e.key.startsWith(NS)) handler(e.key.slice(NS.length));
  };
  channel?.addEventListener("message", onBus);
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    channel?.removeEventListener("message", onBus);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

/* --- identity, moved verbatim from sync.js ------------------------------ */

const FIRST = ["Wren", "Sage", "Milo", "Nora", "Theo", "Ivy", "Reid", "Juno", "Amara", "Cole", "Dara", "Otis"];
const LAST = ["Alvarez", "Boyd", "Castro", "Duval", "Ellery", "Fontaine", "Grady", "Hale", "Ibarra", "Kwan"];
const COLORS = ["#23528f", "#1c6f47", "#9c5f06", "#6b3fa0", "#0d7377", "#a8412c"];

export function identity() {
  const existing = storageRead("me", null);
  if (existing) return existing;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const me = {
    id: "u_" + Math.random().toString(36).slice(2, 9),
    name: pick(FIRST) + " " + pick(LAST),
    color: pick(COLORS),
  };
  storageWrite("me", me);
  return me;
}

export const uid = (p) => p + "_" + Math.random().toString(36).slice(2, 9);

/* --- presence -------------------------------------------------------------

   30 seconds, not an arbitrary round number: mirrors
   api/app/collab/service.py's ACTIVE_WINDOW (ASSUMED_HEARTBEAT_INTERVAL,
   10s, times three heartbeats' worth of slack), so a reviewer who has
   actually left reads as gone on roughly the same timeline a real backend
   would show, rather than the prototype's previous ad hoc 14s. */
const ACTIVE_WINDOW_MS = 30_000;

export function writePresence(sheetId, itemId) {
  const me = identity();
  storageWrite("presence:" + me.id, {
    userId: me.id,
    name: me.name,
    color: me.color,
    sheetId: sheetId ?? null,
    itemId: itemId ?? null,
    seenAt: Date.now(),
  });
}

function listPresenceKeys() {
  // backing has no key()/length API when it's the in-memory fallback, and
  // localStorage's index-based iteration is awkward for a prefix scan
  // either way — keep an explicit index of presence ids instead.
  return storageRead("presence-index", []);
}

export function indexPresence(userId) {
  const ids = listPresenceKeys();
  if (!ids.includes(userId)) storageWrite("presence-index", [...ids, userId]);
}

export function activePresence(excludeUserId) {
  const now = Date.now();
  const ids = listPresenceKeys();
  return ids
    .map((id) => storageRead("presence:" + id, null))
    .filter((p) => p && p.userId !== excludeUserId && now - p.seenAt < ACTIVE_WINDOW_MS);
}
