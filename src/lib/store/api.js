/* ============================================================
   api.js — stub. The real implementation is Task 16's job: every
   method becomes a `fetch` against the endpoints from Tasks 1–14, with
   `credentials: "include"`, mapping the API's snake_case response
   fields to this store's camelCase contract (task-15-brief.md,
   decision 1) and its Decimal-as-string fields
   (quantity/approvedUnits/by_system) to JS numbers at the boundary
   (task-15-report.md).

   Exists now only so src/lib/store/index.js resolves and its branch is
   exercised by VITE_DATA_SOURCE, per the plan's sketch (Task 15, Step
   5, "src/lib/store/index.js").
   ============================================================ */

export function createApiStore() {
  throw new Error("API store arrives in the next task");
}
