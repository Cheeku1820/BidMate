/* ============================================================
   CompanySettings.jsx — spec §5 screen J.

   Tabs with plain-language sections, and every value shows its source
   and last-updated date (spec §5 J). These are the company defaults that
   a project's settings (screen K) resolve against and may override --
   the resolution chain lives in settingsStore.js, not here. No labor or
   pricing values appear in project creation (spec §5 J, §6); they live
   only here.

   The profile, markup, and export tabs still read/write settingsStore.js
   (localStorage) through the generic FIELDS-driven renderer below. Labor
   rates, labor adjustments, and material pricing were migrated off that
   in Task 13: they read and write through `store` (Task 9's
   getCompanyLaborRates/setCompanyLaborRates/getCompanyMaterialPrices/
   setCompanyMaterialPrice/deleteCompanyMaterialPrice), the same real
   backend every other workspace already uses, each with its own load
   effect fired lazily when its tab is first opened -- not eagerly on
   mount -- so a caller that only cares about one of these tabs doesn't
   need to stub store methods for the others.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
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

// Which fields live under which tab, and how each renders. Labor,
// adjustments, and material are handled by their own store-backed
// sections below rather than this generic list -- see LABOR_FIELDS and
// the material tab's dedicated JSX.
const FIELDS = {
  profile: [
    { field: "companyName", label: "Company name", type: "text" },
    { field: "license", label: "Contractor license", type: "text" },
  ],
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

// Labor rates ("labor" tab) and labor adjustments ("adjustments" tab)
// share one company-labor-rates record (Task 9's
// getCompanyLaborRates/setCompanyLaborRates), so both tabs read the same
// local state and this just tells each tab which fields to show from it.
// `api` is the snake_case key the backend's CompanyLaborRatesOut uses
// (api/app/takeoff/schemas.py) -- converted to a Number on load so a
// value like "68.00" displays as "68", matching every other numeric
// field in this file.
const LABOR_FIELDS = {
  labor: [
    { field: "journeymanRate", api: "journeyman_rate", label: "Journeyman rate", prefix: "$", suffix: "/hr" },
    { field: "foremanRate", api: "foreman_rate", label: "Foreman rate", prefix: "$", suffix: "/hr" },
    { field: "apprenticeRate", api: "apprentice_rate", label: "Apprentice rate", prefix: "$", suffix: "/hr" },
  ],
  adjustments: [{ field: "productivityFactor", api: "productivity_factor", label: "Productivity factor", step: "0.05" }],
};

export default function CompanySettings({ store }) {
  const [settings, setSettings] = useState(() => getCompanySettings());
  const [activeTab, setActiveTab] = useState("profile");

  const save = (field, value) => setSettings(setCompanyValue(field, value));

  // ---- Labor rates / labor adjustments (store-backed, Task 13) ----

  const [laborRates, setLaborRates] = useState(null); // null = loading
  const [laborError, setLaborError] = useState(null);

  const loadLaborRates = useCallback(() => {
    setLaborError(null);
    return store
      .getCompanyLaborRates()
      .then((row) => {
        setLaborRates({
          journeymanRate: Number(row.journeyman_rate),
          foremanRate: Number(row.foreman_rate),
          apprenticeRate: Number(row.apprentice_rate),
          productivityFactor: Number(row.productivity_factor),
          updatedAt: row.updated_at,
        });
      })
      .catch((err) => setLaborError(err?.message || "Couldn't load labor rates. Check your connection and try again."));
  }, [store]);

  useEffect(() => {
    if ((activeTab === "labor" || activeTab === "adjustments") && laborRates === null && !laborError) {
      loadLaborRates();
    }
  }, [activeTab, laborRates, laborError, loadLaborRates]);

  const saveLaborRate = async (field, value) => {
    if (!laborRates) return;
    const next = { ...laborRates, [field]: value };
    setLaborError(null);
    try {
      // A full replace (PUT), not a patch -- send every field, not just
      // the one that changed, or the other three would be dropped.
      await store.setCompanyLaborRates({
        journeymanRate: next.journeymanRate,
        foremanRate: next.foremanRate,
        apprenticeRate: next.apprenticeRate,
        productivityFactor: next.productivityFactor,
      });
      await loadLaborRates();
    } catch (err) {
      setLaborError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  // ---- Material pricing (store-backed, Task 13) ----

  const [materialPrices, setMaterialPrices] = useState(null); // null = loading
  const [materialError, setMaterialError] = useState(null);
  const [newMaterialName, setNewMaterialName] = useState("");
  const [newMaterialPrice, setNewMaterialPrice] = useState("");

  const loadMaterialPrices = useCallback(() => {
    setMaterialError(null);
    return store
      .getCompanyMaterialPrices()
      .then((rows) => setMaterialPrices(rows))
      .catch((err) => setMaterialError(err?.message || "Couldn't load material prices. Check your connection and try again."));
  }, [store]);

  useEffect(() => {
    if (activeTab === "material" && materialPrices === null && !materialError) {
      loadMaterialPrices();
    }
  }, [activeTab, materialPrices, materialError, loadMaterialPrices]);

  const addMaterialPrice = async (event) => {
    event.preventDefault();
    const itemName = newMaterialName.trim();
    if (!itemName || newMaterialPrice === "") return;
    const unitPrice = Number(newMaterialPrice);
    if (Number.isNaN(unitPrice)) return;
    setMaterialError(null);
    try {
      await store.setCompanyMaterialPrice(itemName, {
        unitPrice,
        effectiveDate: new Date().toISOString().slice(0, 10),
      });
      setNewMaterialName("");
      setNewMaterialPrice("");
      await loadMaterialPrices();
    } catch (err) {
      setMaterialError(err?.message || "That price couldn't be saved. Try again.");
    }
  };

  const removeMaterialPrice = async (itemName) => {
    setMaterialError(null);
    try {
      await store.deleteCompanyMaterialPrice(itemName);
      await loadMaterialPrices();
    } catch (err) {
      setMaterialError(err?.message || "That price couldn't be removed. Try again.");
    }
  };

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

          {activeTab === "labor" || activeTab === "adjustments" ? (
            laborError ? (
              <div className="load-error" role="alert">
                <p>{laborError}</p>
                <button type="button" className="btn" onClick={loadLaborRates}>
                  Try again
                </button>
              </div>
            ) : laborRates === null ? (
              <p className="muted">Loading labor rates…</p>
            ) : (
              <div className="settings-list">
                {LABOR_FIELDS[activeTab].map((f) => (
                  <div className="settings-row" key={f.field}>
                    <div className="settings-field">
                      <label className="formfield-label" htmlFor={`field-${f.field}`}>
                        {f.label}
                      </label>
                      <div className="settings-input">
                        {f.prefix ? <span className="settings-affix">{f.prefix}</span> : null}
                        <input
                          id={`field-${f.field}`}
                          className="field field--number tabular"
                          type="number"
                          step={f.step}
                          // Uncontrolled, committed on blur -- the same pattern
                          // LaborWorkspace's hours field and MaterialPricing's
                          // price field use. A controlled field committing on
                          // every keystroke fires a PUT and a reload per
                          // character: an estimator typing faster than the round
                          // trip watches the field jump under them, and the last
                          // character can lose the race against the reload and
                          // never reach the server. Keyed on the loaded value so
                          // the field remounts with whatever the store returned.
                          key={laborRates[f.field]}
                          defaultValue={laborRates[f.field]}
                          onBlur={(e) => {
                            // Same empty-field guard as the generic renderer below:
                            // don't persist an empty field as 0.
                            const raw = e.target.value;
                            if (raw === "") return;
                            const n = Number(raw);
                            if (!Number.isNaN(n)) saveLaborRate(f.field, n);
                          }}
                        />
                        {f.suffix ? <span className="settings-affix">{f.suffix}</span> : null}
                      </div>
                    </div>
                    <p className="settings-source muted">
                      Company default · updated {formatCalendarDate(laborRates.updatedAt)}
                    </p>
                  </div>
                ))}
              </div>
            )
          ) : activeTab === "material" ? (
            materialError ? (
              <div className="load-error" role="alert">
                <p>{materialError}</p>
                <button type="button" className="btn" onClick={loadMaterialPrices}>
                  Try again
                </button>
              </div>
            ) : materialPrices === null ? (
              <p className="muted">Loading material prices…</p>
            ) : (
              <>
                {materialPrices.length === 0 ? (
                  <p className="muted">No company material prices yet.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">Item</th>
                        <th scope="col">Unit price</th>
                        <th scope="col">Effective date</th>
                        <th scope="col">Updated</th>
                        <th scope="col">
                          <span className="sr-only">Remove</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {materialPrices.map((row) => (
                        <tr key={row.item_name}>
                          <td>{row.item_name}</td>
                          <td className="tabular">${Number(row.unit_price).toFixed(2)}</td>
                          <td>{formatCalendarDate(row.effective_date)}</td>
                          <td>{formatCalendarDate(row.updated_at)}</td>
                          <td>
                            <button
                              type="button"
                              className="btn btn--danger"
                              onClick={() => removeMaterialPrice(row.item_name)}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}

                <form className="settings-row" onSubmit={addMaterialPrice}>
                  <div className="settings-field">
                    <label className="formfield-label" htmlFor="new-material-name">
                      Item name
                    </label>
                    <input
                      id="new-material-name"
                      className="field"
                      type="text"
                      value={newMaterialName}
                      onChange={(e) => setNewMaterialName(e.target.value)}
                    />
                  </div>
                  <div className="settings-field">
                    <label className="formfield-label" htmlFor="new-material-price">
                      Unit price
                    </label>
                    <div className="settings-input">
                      <span className="settings-affix">$</span>
                      <input
                        id="new-material-price"
                        className="field field--number tabular"
                        type="number"
                        step="0.01"
                        value={newMaterialPrice}
                        onChange={(e) => setNewMaterialPrice(e.target.value)}
                      />
                    </div>
                  </div>
                  <button type="submit" className="btn btn--primary">
                    Add price
                  </button>
                </form>
              </>
            )
          ) : (
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
          )}
        </div>
      </div>
    </>
  );
}
