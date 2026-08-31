/* ============================================================
   detectDocType.js — guess a document's type from its filename.

   Construction sets arrive with descriptive filenames
   ("..._cd_biddrawings.pdf", "specs_part_1.pdf",
   "..._rebid_addendum_01.pdf"), so the type is usually recoverable
   without opening the file. This is a *suggestion*: the upload screen
   pre-selects it and the estimator can override it in the dropdown, per
   spec §5 (detected value the person confirms). It never surfaces model
   names or confidence -- it's just a sensible default.

   Rules are checked in order; the first match wins. Addendum comes first
   because an addendum *to* the drawings or specs is still an addendum.
   ============================================================ */

export const DOC_TYPES = ["Drawings", "Specifications", "Addendum", "Scope", "Other"];

const RULES = [
  { type: "Addendum", keywords: ["addendum", "addenda", "rebid"] },
  {
    type: "Specifications",
    keywords: ["specification", "specs", "spec_", "_spec", "project_manual", "project manual", "projectmanual", "manual", "division 26", "div26", "div_26"],
  },
  { type: "Scope", keywords: ["scope_", "_scope", "scope of work", "scopeofwork", "scope-"] },
  {
    type: "Other",
    keywords: ["geotech", "report", "comment", "record_of", "record of", "bid_tab", "bid tab", "tabulation", "ironworks", "shop", "structural", "-struct", "_struct", "civil", "survey", "narrative"],
  },
  {
    type: "Drawings",
    keywords: ["biddrawing", "bid_drawing", "bid-drawing", "drawing", "as-built", "as_built", "asbuilt", "detail", "_plan", "-plan", "sheet", "_cd_", "-cd-", "_cd-", "blueprint"],
  },
];

/** Like detectDocType, but also reports whether a rule actually matched
 *  (`source: "name"`) or the type fell back to the default
 *  (`source: "default"`). The upload screen uses that to decide whether a
 *  file's name was informative or whether it should peek at the content. */
export function detectDocTypeInfo(filename) {
  const lc = (filename || "").toLowerCase();
  for (const rule of RULES) {
    if (rule.keywords.some((k) => lc.includes(k))) return { type: rule.type, source: "name" };
  }
  return { type: "Drawings", source: "default" };
}

/** Returns the best-guess DOC_TYPE for a filename. Defaults to "Drawings"
 *  -- in a typical set the unlabeled files are the drawing sheets, and a
 *  wrong guess is one dropdown change away from corrected. */
export function detectDocType(filename) {
  return detectDocTypeInfo(filename).type;
}
