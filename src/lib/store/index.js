import { createSeedStore } from "./seed.js";
import { createApiStore } from "./api.js";

/** Swap implementations with VITE_DATA_SOURCE. Removing seed mode later
 *  is deleting seed.js and the branch below (design doc, "Client port"). */
export function createStore() {
  return import.meta.env.VITE_DATA_SOURCE === "api" ? createApiStore() : createSeedStore();
}
