/* ============================================================
   projectStage.js — derived dashboard values.

   The projects table (spec §5.1) and the project overview (spec §6.2)
   both show stage, review progress, and outstanding warnings. Deriving
   them in one place is the same discipline ROADMAP.md invariant 1
   applies to totals: two implementations of one number drift, and the
   estimator has no way to tell which is right.
   ============================================================ */

/** Spec §1's workspace order, collapsed to the positions a project can
 *  actually be reported at. Sentence case, per CLAUDE.md. */
export const STAGES = [
  { key: "setup", label: "Setup" },
  { key: "documents", label: "Documents" },
  { key: "processing", label: "Processing" },
  { key: "review", label: "Review" },
  { key: "pricing", label: "Pricing" },
  { key: "export", label: "Export" },
  { key: "complete", label: "Complete" },
];

const BY_KEY = new Map(STAGES.map((stage) => [stage.key, stage.label]));

/** Unknown stages return their own key rather than throwing or blanking:
 *  the server may learn a stage before this client does, and an empty
 *  column reads as a bug. */
export function stageLabel(key) {
  return BY_KEY.get(key) ?? key;
}

export function reviewProgress(project) {
  const total = project.itemsTotal ?? 0;
  const approved = project.itemsApproved ?? 0;
  return {
    approved,
    total,
    percent: total === 0 ? 0 : Math.round((approved / total) * 100),
  };
}

export function matchesFilter(project, filterKey) {
  const archived = Boolean(project.archivedAt);
  if (filterKey === "archived") return archived;
  if (archived) return false;

  const { approved, total } = reviewProgress(project);
  const fullyApproved = total > 0 && approved === total;

  switch (filterKey) {
    case "active":
      return project.stage !== "complete";
    case "processing":
      return project.stage === "processing";
    case "needsReview":
      return total > 0 && !fullyApproved;
    case "readyToExport":
      // Missing information blocks completion with no override
      // (CLAUDE.md), so a project carrying any is not ready to export no
      // matter what stage it claims.
      return fullyApproved && (project.missingInfo ?? 0) === 0;
    case "complete":
      return project.stage === "complete";
    default:
      return true;
  }
}
