/* ============================================================
   scheduleCopy.js — every string the schedule screen renders.

   Sentence case, the estimator's words. Nothing here names a model, a
   confidence, or a lead time the product invented: a number of weeks
   only ever comes from a row someone entered or a supplier quoted.
   The seeded firm tables are "the default", never "recommended".
   ============================================================ */

export const COPY = {
  title: "Phases and schedule",
  intro: "Hours from the takeoff, placed in time. Every computed value is a starting point you can change.",

  computed: "Computed",
  yours: "Yours",
  defaultSplit: "Default split — set yours in Company settings",
  defaultCrew: "Default crew — set yours in Company settings",
  defaultSplitCount: (n) => `${n} item${n === 1 ? "" : "s"} use${n === 1 ? "s" : ""} the default split`,
  relativeAxis: "Weeks are relative — add a mobilization date in Project settings to see calendar dates.",
  nothingToSchedule: "Nothing to schedule yet. Labor hours come from the Labor workspace.",
  noDemolition: "No demolition items yet",

  addPhase: "Add phase",
  phaseName: "Phase name",
  assignSheets: "Assign sheets",
  moveSheets: "Move sheets",
  deletePhase: "Remove phase",
  deletePhaseConfirm: (name, target) => `Remove ${name}? Its sheets move to ${target}. This can be undone.`,
  proposeFromSheets: "Propose phases from sheet numbers",
  confirmProposal: "Set up these phases",
  dismiss: "Dismiss",

  resetToComputed: "Reset to computed",
  toFinishBy: (n, stage, date) => `To finish by ${date}: ${n} on ${stage.toLowerCase()}`,
  applyCrew: (n) => `Apply ${n} as the crew`,
  peakAverage: (peak, week, average) => `Peak ${peak} on site in week ${week}; average ${average}`,

  longLead: "Long-lead items",
  notYetQuoted: "Not yet quoted",
  notYetQuotedFix: "Ask the supplier for a lead time, or upload their price sheet with the lead-time column filled.",
  typeLeadTime: "Type a lead time",
  weeks: "Weeks",
  whoSaidSo: "Who quoted it",
  quotedOn: "Quoted on",
  saveLeadTime: "Save lead time",
  flagLongLead: "Flag an item as long-lead",
  unflagLongLead: "Not long-lead",
  neededFor: "Needed for",
  orderBy: "Order by",
  clear: "Clear",
  sourceTag: (source, label, date) =>
    source === "company" ? `Company: ${label}, ${date}` : `${label}, ${date}`,

  generalConditions: "General conditions",
  directHours: "Direct hours",
  start: "Start",
  requiredFinish: "Required finish",
  movedIn: (n) => `${n} item${n === 1 ? "" : "s"} moved in`,
  movedOut: (n) => `${n} item${n === 1 ? "" : "s"} moved out`,

  phaseField: "Phase",
  phaseInherited: "From its sheet",
  phaseMoved: (from) => `moved from ${from}`,

  loadError: "Couldn't load the schedule. Check your connection and try again.",
  saveError: "This change could not be saved.",
};
