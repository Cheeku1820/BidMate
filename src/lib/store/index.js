import { createApiStore } from "./api.js";

/** One data source. The seed/localStorage store this used to choose
 *  between was deleted in the API-only slice — see
 *  docs/superpowers/specs/2026-08-27-api-only-foundation-design.md. */
export function createStore() {
  return createApiStore();
}
