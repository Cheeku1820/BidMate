import { createApiStore } from "./api.js";

/** One data source. The seed/localStorage store this used to choose
 *  between was deleted in the API-only slice — see
 *  docs/specs/api-only-foundation.md. */
export function createStore() {
  return createApiStore();
}
