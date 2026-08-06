/* ============================================================
   sync.js — shared-state layer for the prototype.

   Real product: this would be a websocket/CRDT service. Here it is
   localStorage + BroadcastChannel, which gives a genuine multi-user
   demo across browser tabs and windows on one machine — presence,
   live edits, and a shared undo stack all behave the way they would
   against a server.
   ============================================================ */

const NS = "takeoff-review:";

let channel = null;
try {
  channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(NS + "bus") : null;
} catch {
  channel = null;
}

/* Sandboxed frames block localStorage. Fall back to an in-memory map so the
   app still runs end to end — it just loses cross-tab sync and persistence. */
const memory = new Map();
const store = (() => {
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
      key: (i) => Array.from(memory.keys())[i] ?? null,
      get length() {
        return memory.size;
      },
    };
  }
})();

export const isPersistent = store === (typeof localStorage !== "undefined" ? localStorage : null);

export function read(key, fallback) {
  try {
    const raw = store.getItem(NS + key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

export function write(key, value) {
  try {
    store.setItem(NS + key, JSON.stringify(value));
    channel?.postMessage({ key, at: Date.now() });
    return true;
  } catch {
    return false;
  }
}

export function subscribe(handler) {
  const onBus = (e) => handler(e.data?.key);
  const onStorage = (e) => {
    if (e.key && e.key.startsWith(NS)) handler(e.key.slice(NS.length));
  };
  channel?.addEventListener("message", onBus);
  window.addEventListener("storage", onStorage);
  return () => {
    channel?.removeEventListener("message", onBus);
    window.removeEventListener("storage", onStorage);
  };
}

export function listKeys(prefix) {
  const out = [];
  for (let i = 0; i < store.length; i += 1) {
    const k = store.key(i);
    if (k && k.startsWith(NS + prefix)) out.push(k.slice(NS.length));
  }
  return out;
}

export function removeKey(key) {
  try {
    store.removeItem(NS + key);
  } catch {
    /* ignore */
  }
}

/* --- identity ------------------------------------------------ */

const FIRST = ["Wren", "Sage", "Milo", "Nora", "Theo", "Ivy", "Reid", "Juno", "Amara", "Cole", "Dara", "Otis"];
const LAST = ["Alvarez", "Boyd", "Castro", "Duval", "Ellery", "Fontaine", "Grady", "Hale", "Ibarra", "Kwan"];
const COLORS = ["#23528f", "#1c6f47", "#9c5f06", "#6b3fa0", "#0d7377", "#a8412c"];

export function identity() {
  const existing = read("me", null);
  if (existing) return existing;
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  const me = {
    id: "u_" + Math.random().toString(36).slice(2, 9),
    name: pick(FIRST) + " " + pick(LAST),
    color: pick(COLORS),
  };
  write("me", me);
  return me;
}

export function initials(name) {
  return name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
