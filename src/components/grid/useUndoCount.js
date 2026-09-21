/* ============================================================
   useUndoCount.js — how many undo() calls the toast's Undo stands
   for (docs/specs/spreadsheet-grid.md, "The toast, and the undo of a
   range operation").

   A range operation lands as N store calls, each its own action on
   the project's shared undo stack. Its toast's Undo reverses all of
   them: undo() N times, newest first, then a reload, then one toast
   naming the count. A single-cell commit is the same path with N = 1.
   The count is a ref, not state: it is written right before showToast
   and read only from the toast's button.
   ============================================================ */

import { useCallback, useRef } from "react";
import { reversedToast } from "./rangeCopy.js";

const ONE = { calls: 1, cells: 1 };

export function useUndoCount({ undo, load, showToast }) {
  const count = useRef(ONE);

  const remember = useCallback(({ calls, cells }) => {
    count.current = { calls, cells };
  }, []);

  const undoLast = useCallback(async () => {
    const { calls, cells } = count.current;
    count.current = ONE;
    for (let i = 0; i < calls; i += 1) {
      const res = await undo();
      if (res && res.performed === false) break;
    }
    await load();
    if (calls > 1) showToast(reversedToast(cells));
  }, [undo, load, showToast]);

  return { remember, undoLast };
}
