/* ============================================================
   vocabulary.js — the four review labels, their order, and the system
   list. The spine CLAUDE.md protects: four statuses, never a fifth.

   Split out of the former data.js, which carried this alongside the
   twelve-item seed fixture. The fixture is gone; the vocabulary is not
   fixture data and never was.
   ============================================================ */

export const STATUS = {
  ready: { key: "ready", label: "Ready to review", color: "#23528f", tint: "#e8f0fa" },
  attention: { key: "attention", label: "Needs attention", color: "#9c5f06", tint: "#fbf0dc" },
  missing: { key: "missing", label: "Missing information", color: "#b0322a", tint: "#fbe9e7" },
  approved: { key: "approved", label: "Estimator approved", color: "#1c6f47", tint: "#e6f3ec" },
  rejected: { key: "rejected", label: "Rejected", color: "#86827a", tint: "#f7f5f0" },
};

export const STATUS_ORDER = ["missing", "attention", "ready", "approved", "rejected"];

export const SYSTEMS = ["Power", "Lighting", "Distribution", "Life safety", "Low voltage", "Fire alarm"];
