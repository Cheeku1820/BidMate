/* ============================================================
   CompanySettings.jsx — spec §5 screen J.

   Tabs with plain-language sections, and every value shows its source
   and last-updated date (spec §5 J). These are the company defaults that
   a project's settings (screen K) resolve against and may override --
   the resolution chain lives in settingsStore.js, not here. Edits
   persist to localStorage the same way the rest of seed mode does, so
   the screen is genuinely functional rather than a static mock. No labor
   or pricing values appear in project creation (spec §5 J, §6); they
   live only here.
   ============================================================ */

import { useState } from "react";
import AppTopBar from "../shell/AppTopBar.jsx";
import { getCompanySettings, setCompanyValue } from "../../lib/settingsStore.js";
import { formatCalendarDate } from "../../lib/format.js";

const TABS = [
  { id: "profile", label: "Company profile", intro: "Your firm's identity, shown on exports." },
  { id: "labor", label: "Labor rates", intro: "Hourly rates applied to estimated labor hours." },
  { id: "adjustments", label: "Labor adjustments", intro: "Productivity factors applied on top of base hours." },
  { id: "material", label: "Material pricing", intro: "Where material unit costs and labor units come from." },
  { id: "markup", label: "Waste and markup", intro: "The estimator-owned layer on top of direct cost." },
  { id: "export", label: "Export preferences", intro: "Defaults for the exported workbook." },
];

// Which fields live under which tab, and how each renders.
const FIELDS = {
  profile: [
    { field: "companyName", label: "Company name", type: "text" },
    { field: "license", label: "Contractor license", type: "text" },
  ],
  labor: [
    { field: "journeymanRate", label: "Journeyman rate", type: "number", prefix: "$", suffix: "/hr" },
    { field: "foremanRate", label: "Foreman rate", type: "number", prefix: "$", suffix: "/hr" },
    { field: "apprenticeRate", label: "Apprentice rate", type: "number", prefix: "$", suffix: "/hr" },
  ],
  adjustments: [{ field: "productivityFactor", label: "Productivity factor", type: "number", step: "0.05" }],
  material: [{ field: "materialSource", label: "Pricing source", type: "text" }],
  markup: [
    { field: "wastePercent", label: "Waste", type: "number", suffix: "%" },
    { field: "overheadPercent", label: "Overhead", type: "number", suffix: "%" },
    { field: "profitPercent", label: "Profit", type: "number", suffix: "%" },
  ],
  export: [
    { field: "exportFormat", label: "Export format", type: "select", options: ["Excel (.xlsx)", "CSV (.csv)"] },
    { field: "includeSourceRefs", label: "Include source sheet references", type: "boolean" },
  ],
};

export default function CompanySettings() {
  const [settings, setSettings] = useState(() => getCompanySettings());
  const [activeTab, setActiveTab] = useState("profile");

  const save = (field, value) => setSettings(setCompanyValue(field, value));

  const tab = TABS.find((t) => t.id === activeTab);
  const fields = FIELDS[activeTab] ?? [];

  return (
    <>
      <AppTopBar title="Company settings" />

      <div className="page">
        <h1 className="page-heading">Company settings</h1>

        <div className="tabs" role="tablist" aria-label="Company settings sections">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={t.id === activeTab}
              aria-controls={`panel-${t.id}`}
              className={t.id === activeTab ? "tab is-active" : "tab"}
              onClick={() => setActiveTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>

        <div className="tabpanel" role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
          <p className="muted">{tab.intro}</p>

          <div className="settings-list">
            {fields.map((f) => {
              const entry = settings[f.field];
              return (
                <div className="settings-row" key={f.field}>
                  <div className="settings-field">
                    <label className="formfield-label" htmlFor={`field-${f.field}`}>
                      {f.label}
                    </label>
                    <div className="settings-input">
                      {f.prefix ? <span className="settings-affix">{f.prefix}</span> : null}
                      {f.type === "boolean" ? (
                        <label className="switch">
                          <input
                            id={`field-${f.field}`}
                            type="checkbox"
                            checked={Boolean(entry.value)}
                            onChange={(e) => save(f.field, e.target.checked)}
                          />
                          {entry.value ? "On" : "Off"}
                        </label>
                      ) : f.type === "select" ? (
                        <select
                          id={`field-${f.field}`}
                          className="field"
                          value={entry.value}
                          onChange={(e) => save(f.field, e.target.value)}
                        >
                          {f.options.map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={`field-${f.field}`}
                          className={f.type === "number" ? "field field--number tabular" : "field"}
                          type={f.type}
                          step={f.step}
                          value={entry.value}
                          onChange={(e) => {
                            if (f.type !== "number") {
                              save(f.field, e.target.value);
                              return;
                            }
                            // Don't persist an empty field as 0 -- Number("")
                            // is 0, which would silently write a $0/hr rate or
                            // a 0% markup. Only commit a real number.
                            const raw = e.target.value;
                            if (raw === "") return;
                            const n = Number(raw);
                            if (!Number.isNaN(n)) save(f.field, n);
                          }}
                        />
                      )}
                      {f.suffix ? <span className="settings-affix">{f.suffix}</span> : null}
                    </div>
                  </div>
                  <p className="settings-source muted">
                    Company default · updated {formatCalendarDate(entry.updatedAt)}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}
