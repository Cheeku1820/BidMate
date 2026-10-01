/* ============================================================
   useUndoCount.js — how many undo() calls the toast's Undo stands
   for (docs/specs/spreadsheet-grid.md, "The toast, and the undo of a
   range operation").

   A range operation lands as N store calls, each its own action on
   the project's shared undo stack. Its toast's Undo reverses all of
   them: undo() N times, newest first, then a reload, then one toast
   naming the count. A single-cell commit is the same path with N = 1.

   The count is a ref, not state, written right before showToast and
   read only from the toast's button -- but a screen shows more toasts
   than the ones this hook remembers ("Undid…"/"Redid…" from Ctrl+Z,
   "Applied supplier pricing for N items", REFRESH_BUSY…), and every
   one of them renders the same Undo button. remember() is keyed to
   the exact toast text it was set for, and undoLast(text) only trusts
   the remembered count when the toast on screen still carries that
   text; any other toast's Undo reverses a single action, same as if
   nothing had ever been remembered. Whoever calls remember() passes
   the same string it is about to hand showToast().
   ============================================================ */

import { useCallback, useRef } from "react";
import { reversedToast } from "./rangeCopy.js";

const ONE = { calls: 1, cells: 1, text: undefined };

export function useUndoCount({ undo, load, showToast }) {
  const count = useRef(ONE);

  const remember = useCallback(({ calls, cells, text }) => {
    count.current = { calls, cells, text };
  }, []);

  const undoLast = useCallback(
    async (text) => {
      const remembered = count.current;
      const { calls, cells } = text !== undefined && text === remembered.text ? remembered : ONE;
      count.current = ONE;
      try {
        for (let i = 0; i < calls; i += 1) {
          const res = await undo();
          if (res && res.performed === false) break;
        }
      } finally {
        await load();
      }
      if (calls > 1) showToast(reversedToast(cells));
    },
    [undo, load, showToast],
  );

  return { remember, undoLast };
}
