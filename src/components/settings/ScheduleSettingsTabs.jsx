/* ============================================================
   ScheduleSettingsTabs.jsx — the firm's schedule tables, as two tabs of
   Company settings (phases-and-timeline.md §3.3, §3.4, §7.2).

   Kept in its own file rather than grown into CompanySettings.jsx: that
   file already carries five tabs' worth of state, and these two have
   their own tables, their own validation, and their own audit path
   (a company edit is recorded and deliberately not undoable).

   A row the firm has never touched is labelled "Default" — never
   "recommended" and never an industry claim. The lead-time tab holds
   only what somebody actually quoted: a blank row reads "Not entered",
   and nothing here invents a number of weeks.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { LONG_LEAD_CLASSES, STAGES, stageLabel } from "../schedule/stages.js";

const SPLIT_FIELDS = [
  { key: "demolition", label: "Demolition" },
  { key: "roughIn", label: "Rough-in" },
  { key: "wirePull", label: "Wire pull" },
  { key: "gear", label: "Gear" },
  { key: "trim", label: "Trim" },
  { key: "closeout", label: "Close-out" },
];

const CREW_FIELDS = [
  { key: "foreman", label: "Foreman", kind: "int" },
  { key: "journeyman", label: "Journeyman", kind: "int" },
  { key: "apprentice", label: "Apprentice", kind: "int" },
  { key: "productiveHoursPerDay", label: "Hours per day", kind: "decimal" },
  { key: "productivityFactor", label: "Productivity", kind: "decimal" },
  { key: "maxCrew", label: "Most on one stage", kind: "int" },
];

const SPLIT_TOTAL_MESSAGE = "The six stages have to add up to 100 percent.";

function toWire(row) {
  return {
    categoryLabel: row.categoryLabel,
    demolition: row.demolition,
    roughIn: row.roughIn,
    wirePull: row.wirePull,
    gear: row.gear,
    trim: row.trim,
    closeout: row.closeout,
  };
}

function splitTotal(row) {
  return SPLIT_FIELDS.reduce((sum, field) => sum + Number(row[field.key] || 0), 0);
}

export function CrewsAndStagesTab({ store }) {
  const [splits, setSplits] = useState(null);
  const [crews, setCrews] = useState(null);
  const [staleDays, setStaleDays] = useState("");
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [splitRows, crewRows, settings] = await Promise.all([
        store.getStageSplits(),
        store.getStageCrews(),
        store.getScheduleSettings(),
      ]);
      setSplits(splitRows);
      setCrews(crewRows);
      setStaleDays(String(settings.leadTimeStaleDays));
    } catch (err) {
      setError(err?.message || "Couldn't load the firm's crews and stages. Try again.");
    }
  }, [store]);

  useEffect(() => {
    load();
  }, [load]);

  async function saveSplit(row) {
    if (splitTotal(row) !== 100) {
      setError(SPLIT_TOTAL_MESSAGE);
      return;
    }
    setError(null);
    try {
      const updated = await store.setStageSplit(row.categoryKey, toWire(row));
      setSplits((rows) => rows.map((r) => (r.categoryKey === updated.categoryKey ? updated : r)));
      setSaved(`Saved the ${updated.categoryLabel.toLowerCase()} split`);
    } catch (err) {
      setError(err?.message || "That split couldn't be saved. Try again.");
    }
  }

  async function saveCrew(row) {
    setError(null);
    try {
      const updated = await store.setStageCrew(row.stage, {
        foreman: row.foreman,
        journeyman: row.journeyman,
        apprentice: row.apprentice,
        productiveHoursPerDay: row.productiveHoursPerDay,
        productivityFactor: row.productivityFactor,
        maxCrew: row.maxCrew,
      });
      setCrews((rows) => rows.map((r) => (r.stage === updated.stage ? updated : r)));
      setSaved(`Saved the ${stageLabel(updated.stage).toLowerCase()} crew`);
    } catch (err) {
      setError(err?.message || "That crew couldn't be saved. Try again.");
    }
  }

  async function saveStaleDays(value) {
    const days = Number(value);
    if (!Number.isInteger(days) || days < 1) return;
    try {
      await store.setScheduleSettings({ leadTimeStaleDays: days });
      setSaved(`Lead times count as out of date after ${days} days`);
    } catch (err) {
      setError(err?.message || "That setting couldn't be saved. Try again.");
    }
  }

  if (error && splits === null) {
    return (
      <div className="load-error" role="alert">
        <p>{error}</p>
        <button type="button" className="btn" onClick={load}>Try again</button>
      </div>
    );
  }
  if (splits === null || crews === null) return <p className="muted">Loading crews and stages…</p>;

  return (
    <div className="schedule-settings">
      {error ? <p role="alert" className="error-text">{error}</p> : null}
      {saved ? <p className="muted" role="status">{saved}</p> : null}

      <h2>How an item's hours divide across the stages</h2>
      <table className="settings-table">
        <thead>
          <tr>
            <th scope="col">Category</th>
            {SPLIT_FIELDS.map((field) => <th key={field.key} scope="col">{field.label}</th>)}
            <th scope="col">Total</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {splits.map((row) => {
            const total = splitTotal(row);
            return (
              <tr key={row.categoryKey}>
                <th scope="row">
                  {row.categoryKey === "*" ? "Anything else" : row.categoryLabel}
                  {row.firmEdited ? null : <span className="tier-tag">Default</span>}
                </th>
                {SPLIT_FIELDS.map((field) => (
                  <td key={field.key}>
                    <input
                      className="field field--number tabular"
                      type="text"
                      inputMode="decimal"
                      aria-label={`${row.categoryLabel} ${field.label}`}
                      value={row[field.key]}
                      onChange={(event) =>
                        setSplits((rows) =>
                          rows.map((r) =>
                            r.categoryKey === row.categoryKey
                              ? { ...r, [field.key]: event.target.value.replace(/[^\d.]/g, "") }
                              : r,
                          ),
                        )
                      }
                    />
                  </td>
                ))}
                <td className={total === 100 ? "tabular" : "tabular error-text"}>{total}</td>
                <td>
                  <button type="button" className="btn" onClick={() => saveSplit(row)}>Save</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>The crew the firm puts on each stage</h2>
      <table className="settings-table">
        <thead>
          <tr>
            <th scope="col">Stage</th>
            {CREW_FIELDS.map((field) => <th key={field.key} scope="col">{field.label}</th>)}
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {STAGES.map((stage) => {
            const row = crews.find((r) => r.stage === stage);
            if (!row) return null;
            return (
              <tr key={stage}>
                <th scope="row">
                  {stageLabel(stage)}
                  {row.firmEdited ? null : <span className="tier-tag">Default</span>}
                </th>
                {CREW_FIELDS.map((field) => (
                  <td key={field.key}>
                    <input
                      className="field field--number tabular"
                      type="text"
                      inputMode={field.kind === "int" ? "numeric" : "decimal"}
                      aria-label={`${stageLabel(stage)} ${field.label}`}
                      value={row[field.key]}
                      onChange={(event) =>
                        setCrews((rows) =>
                          rows.map((r) =>
                            r.stage === stage ? { ...r, [field.key]: event.target.value.replace(/[^\d.]/g, "") } : r,
                          ),
                        )
                      }
                    />
                  </td>
                ))}
                <td>
                  <button type="button" className="btn" onClick={() => saveCrew(row)}>Save</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="settings-row">
        <div className="settings-field">
          <label className="formfield-label" htmlFor="stale-days">
            Lead times count as out of date after
          </label>
          <div className="settings-input">
            <input
              id="stale-days"
              className="field field--number tabular"
              type="text"
              inputMode="numeric"
              value={staleDays}
              onChange={(event) => setStaleDays(event.target.value.replace(/\D/g, ""))}
              onBlur={(event) => saveStaleDays(event.target.value)}
            />
            <span className="settings-affix">days</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function LeadTimesTab({ store }) {
  const [rows, setRows] = useState(null);
  const [draft, setDraft] = useState({});
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await store.getCompanyLeadTimes());
    } catch (err) {
      setError(err?.message || "Couldn't load the firm's lead times. Try again.");
    }
  }, [store]);

  useEffect(() => {
    load();
  }, [load]);

  function draftFor(itemClass) {
    const stored = rows?.find((row) => row.itemClass === itemClass);
    return (
      draft[itemClass] ?? {
        leadWeeks: stored ? String(stored.leadWeeks) : "",
        sourceLabel: stored?.sourceLabel ?? "",
        quotedAt: stored?.quotedAt ?? new Date().toISOString().slice(0, 10),
      }
    );
  }

  function edit(itemClass, changes) {
    setDraft((current) => ({ ...current, [itemClass]: { ...draftFor(itemClass), ...changes } }));
  }

  async function save(itemClass) {
    const values = draftFor(itemClass);
    if (!values.leadWeeks || !values.sourceLabel.trim() || !values.quotedAt) return;
    try {
      const saved = await store.setCompanyLeadTime(itemClass, {
        leadWeeks: Number(values.leadWeeks),
        sourceLabel: values.sourceLabel.trim(),
        quotedAt: values.quotedAt,
      });
      setRows((current) => [...current.filter((row) => row.itemClass !== itemClass), saved]);
      setDraft((current) => ({ ...current, [itemClass]: undefined }));
    } catch (err) {
      setError(err?.message || "That lead time couldn't be saved. Try again.");
    }
  }

  async function clear(itemClass) {
    try {
      await store.deleteCompanyLeadTime(itemClass);
      setRows((current) => current.filter((row) => row.itemClass !== itemClass));
      setDraft((current) => ({ ...current, [itemClass]: undefined }));
    } catch (err) {
      setError(err?.message || "That lead time couldn't be removed. Try again.");
    }
  }

  if (error && rows === null) {
    return (
      <div className="load-error" role="alert">
        <p>{error}</p>
        <button type="button" className="btn" onClick={load}>Try again</button>
      </div>
    );
  }
  if (rows === null) return <p className="muted">Loading lead times…</p>;

  return (
    <div className="schedule-settings">
      {error ? <p role="alert" className="error-text">{error}</p> : null}
      <table className="settings-table">
        <thead>
          <tr>
            <th scope="col">Equipment</th>
            <th scope="col">Weeks</th>
            <th scope="col">Who quoted it</th>
            <th scope="col">Quoted on</th>
            <th scope="col" />
          </tr>
        </thead>
        <tbody>
          {LONG_LEAD_CLASSES.map(({ key, label }) => {
            const stored = rows.find((row) => row.itemClass === key);
            const values = draftFor(key);
            return (
              <tr key={key}>
                <th scope="row">
                  {label}
                  {stored ? null : <span className="muted"> — Not entered</span>}
                </th>
                <td>
                  <input
                    className="field field--number tabular"
                    type="text"
                    inputMode="numeric"
                    aria-label={`${label} weeks`}
                    value={values.leadWeeks}
                    onChange={(event) => edit(key, { leadWeeks: event.target.value.replace(/\D/g, "") })}
                  />
                </td>
                <td>
                  <input
                    className="field"
                    type="text"
                    aria-label={`${label} who quoted it`}
                    value={values.sourceLabel}
                    onChange={(event) => edit(key, { sourceLabel: event.target.value })}
                  />
                </td>
                <td>
                  <input
                    className="field"
                    type="date"
                    aria-label={`${label} quoted on`}
                    value={values.quotedAt}
                    onChange={(event) => edit(key, { quotedAt: event.target.value })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn"
                    disabled={!values.leadWeeks || !values.sourceLabel.trim()}
                    onClick={() => save(key)}
                  >
                    Save
                  </button>
                  {stored ? (
                    <button type="button" className="link" onClick={() => clear(key)}>Clear</button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
