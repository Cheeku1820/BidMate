/** Copy for "find every one like this" (B3b spec §9). Sentence case,
 *  plain construction terms, no processing internals. */
export const DRAW_PROMPT = "Drag a box around one symbol";
export const SEARCHING = "Searching this sheet…";
export const NONE_FOUND = "No other symbols like this were found";
export const NOTHING_FOUND = "No symbols like this were found";
export const NOTHING_FOUND_FIX = "Draw the box more tightly around one symbol and try again.";
export const NOT_SURE = "Not sure yet";
export const found = (n) => `${n} ${n === 1 ? "match" : "matches"} found`;
export const addLabel = (n) => `Add ${n} to the takeoff`;
