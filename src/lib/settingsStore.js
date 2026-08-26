/* ============================================================
   settingsStore.js — client persistence for company and project
   settings (spec §5 screens J and K).

   Seed mode's whole premise is that localStorage stands in for a backend
   (CLAUDE.md, "Sync is single-machine"), so these settings persist there
   too rather than resetting on reload -- that is what makes the screens
   genuinely functional rather than a static mock. A production build
   would move this behind the identity/company services; the shape here
   is the resolution chain those will need: a company default, and a
   per-project override that falls back to it.

   The one rule the settings screens rest on (spec §5, §6): a project
   value is either its company default or an explicit override, and an
   override can always be restored to the default. resolveProject() below
   is where that chain lives, so no screen re-implements it.
   ============================================================ */

const COMPANY_KEY = "bidmate:company-settings";
const PROJECT_KEY = "bidmate:project-settings";

// Company defaults, each carrying its own source label and a last-updated
// stamp so the screens can show where a value came from (spec §5 J: "show
// each value's source and last-updated date"). The date is fixed rather
// than Date.now() so it reads as a real prior edit, not "just now".
export const COMPANY_DEFAULTS = {
  companyName: { value: "Meridian Electric Co.", updatedAt: "2026-05-02" },
  license: { value: "C-10 #984120", updatedAt: "2026-05-02" },
  journeymanRate: { value: 68, updatedAt: "2026-06-14" },
  foremanRate: { value: 82, updatedAt: "2026-06-14" },
  apprenticeRate: { value: 41, updatedAt: "2026-06-14" },
  productivityFactor: { value: 1.0, updatedAt: "2026-06-14" },
  materialSource: { value: "NECA labor units · Q2 2026", updatedAt: "2026-04-30" },
  wastePercent: { value: 3, updatedAt: "2026-05-02" },
  overheadPercent: { value: 12, updatedAt: "2026-05-02" },
  profitPercent: { value: 10, updatedAt: "2026-05-02" },
  exportFormat: { value: "Excel (.xlsx)", updatedAt: "2026-05-02" },
  includeSourceRefs: { value: true, updatedAt: "2026-05-02" },
};

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Sandboxed frames block localStorage; a settings edit that can't
    // persist is a no-op rather than a crash.
  }
}

const today = () => new Date().toISOString().slice(0, 10);

/** The company settings, defaults overlaid with any saved edits. */
export function getCompanySettings() {
  const saved = read(COMPANY_KEY, {});
  const merged = {};
  for (const [field, def] of Object.entries(COMPANY_DEFAULTS)) {
    merged[field] = saved[field] ? { ...def, ...saved[field] } : def;
  }
  return merged;
}

export function setCompanyValue(field, value) {
  const saved = read(COMPANY_KEY, {});
  saved[field] = { value, updatedAt: today() };
  write(COMPANY_KEY, saved);
  return getCompanySettings();
}

/** The per-project overrides map: `{ [field]: value }`, only for fields
 *  the project has explicitly overridden. */
function getProjectOverrides(projectId) {
  const all = read(PROJECT_KEY, {});
  return all[projectId] ?? {};
}

/** Resolves a project's effective settings: the company default for each
 *  field, replaced by an override where one exists. Each entry reports
 *  whether it is `overridden`, so the screen can show "Restore company
 *  default" only where it applies. */
export function resolveProject(projectId) {
  const company = getCompanySettings();
  const overrides = getProjectOverrides(projectId);
  const resolved = {};
  for (const [field, def] of Object.entries(company)) {
    const overridden = Object.prototype.hasOwnProperty.call(overrides, field);
    resolved[field] = {
      value: overridden ? overrides[field] : def.value,
      source: overridden ? "Project override" : "Company default",
      overridden,
      companyValue: def.value,
    };
  }
  return resolved;
}

export function setProjectOverride(projectId, field, value) {
  const all = read(PROJECT_KEY, {});
  all[projectId] = { ...(all[projectId] ?? {}), [field]: value };
  write(PROJECT_KEY, all);
  return resolveProject(projectId);
}

export function restoreCompanyDefault(projectId, field) {
  const all = read(PROJECT_KEY, {});
  if (all[projectId]) {
    delete all[projectId][field];
    write(PROJECT_KEY, all);
  }
  return resolveProject(projectId);
}
