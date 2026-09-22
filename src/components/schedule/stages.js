/* ============================================================
   stages.js — the six stages of electrical work, mirroring
   api/app/schedule/stages.py.

   The order is the order the work runs in per area (demolition first
   on a renovation, close-out last), and these labels are the only
   words the screen uses for a stage. A stage is not a review label:
   it describes when hours land, never an item's evidence.
   ============================================================ */

export const STAGES = ["demolition", "rough_in", "wire_pull", "gear", "trim", "closeout"];

export const STAGE_LABELS = {
  demolition: "Demolition",
  rough_in: "Rough-in",
  wire_pull: "Wire pull",
  gear: "Gear",
  trim: "Trim",
  closeout: "Close-out",
};

/** Unknown keys return themselves rather than blanking: the server may
 *  learn a stage before this file does, and an empty bar reads as a bug.
 *  (Same rule projectStage.js's stageLabel follows.) */
export function stageLabel(key) {
  return STAGE_LABELS[key] ?? key;
}

export const ROLES = [
  { key: "foreman", label: "Foreman", short: "F" },
  { key: "journeyman", label: "Journeyman", short: "J" },
  { key: "apprentice", label: "Apprentice", short: "A" },
];

/** "1F 2J 2A" — the crew as a bar labels it. */
export function crewText(crew) {
  return ROLES.map((role) => `${crew?.[role.key] ?? 0}${role.short}`).join(" ");
}

/** The long-lead classes the API recognises, with the estimator's word
 *  for each. Mirrors LONG_LEAD_CLASSES in api/app/schedule/stages.py. */
export const LONG_LEAD_CLASSES = [
  { key: "switchboard", label: "Switchboards" },
  { key: "switchgear", label: "Switchgear" },
  { key: "mcc", label: "Motor control centers" },
  { key: "transformer", label: "Transformers" },
  { key: "generator", label: "Generators" },
  { key: "ats", label: "Transfer switches" },
  { key: "busway", label: "Busway" },
  { key: "panelboard", label: "Panelboards" },
];
