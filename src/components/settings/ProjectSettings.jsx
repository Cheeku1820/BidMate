/* ============================================================
   ProjectSettings.jsx — spec §5 screen K.

   Project details, plus the estimator-owned settings layer resolved
   against the company defaults (screen J). The rule this screen is built
   around: every override offers "Restore company default" (spec §5 K),
   and a value plainly shows whether it is the company default or a
   project override (spec §6). The resolution and the restore both go
   through settingsStore.js, so the chain is written once.

   Audit history is named here as the action log the review workspace
   already keeps, rather than invented as a second record -- the honest
   place a project's changes live today (ROADMAP.md, "The action log").
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { resolveProject, setProjectOverride, restoreCompanyDefault } from "../../lib/settingsStore.js";
import { formatCalendarDate, NOT_SET, saveStateText } from "../../lib/format.js";

// Five digits or empty -- the same shape PostalCodeIn (schemas.py)
// accepts. Checked here too so a malformed ZIP never reaches the wire
// and shows an estimator-facing reason inline, at the field, rather
// than as a rejected-request message with no recovery action named.
const ZIP_PATTERN = /^\d{5}$/;

// The estimator-owned values a project may override. Details (name,
// address) are project facts, not overrides, so they render separately.
const OVERRIDABLE = [
  { field: "journeymanRate", label: "Journeyman rate", prefix: "$", suffix: "/hr" },
  { field: "foremanRate", label: "Foreman rate", prefix: "$", suffix: "/hr" },
  { field: "apprenticeRate", label: "Apprentice rate", prefix: "$", suffix: "/hr" },
  { field: "productivityFactor", label: "Productivity factor", step: "0.05" },
  { field: "wastePercent", label: "Waste", suffix: "%" },
  { field: "overheadPercent", label: "Overhead", suffix: "%" },
  { field: "profitPercent", label: "Profit", suffix: "%" },
];

export default function ProjectSettings({ store }) {
  const { projectId } = useParams();
  const [project, setProject] = useState(null);
  const [state, setState] = useState("loading");
  const [errorMessage, setErrorMessage] = useState(null);
  const [resolved, setResolved] = useState(() => resolveProject(projectId));

  // The ZIP field: this screen isn't routed inside ProjectWorkspaceLayout
  // (it's the estimator's own listProjects fetch, not the polled review
  // snapshot -- see the load() below), so there's no useWorkspaceContext()
  // to borrow runMutation/showToast from. Its own save-state and toast
  // follow the identical convention (DESIGN.md's Saving…/Saved rhythm,
  // the pricing screens' five-second toast) rather than a different one.
  const [postalCode, setPostalCodeValue] = useState("");
  const [savedPostalCode, setSavedPostalCode] = useState("");
  const [zipError, setZipError] = useState(null);
  const [saved, setSaved] = useState(null);
  const [toast, setToast] = useState(null);

  const showToast = useCallback((text) => {
    const id = Date.now();
    setToast({ id, text });
    setTimeout(() => setToast((t) => (t && t.id === id ? null : t)), 5000);
  }, []);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(() => {
    setState("loading");
    setErrorMessage(null);
    store
      .listProjects({ includeArchived: true })
      .then((rows) => {
        if (!mountedRef.current) return;
        const found = rows.find((row) => row.id === projectId);
        setProject(found ?? null);
        setPostalCodeValue(found?.postalCode ?? "");
        setSavedPostalCode(found?.postalCode ?? "");
        setState(found ? "ready" : "missing");
      })
      .catch((err) => {
        if (!mountedRef.current) return;
        setErrorMessage(err?.message || "The project couldn't be loaded. Try again.");
        setState("error");
      });
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const override = (field, value) => setResolved(setProjectOverride(projectId, field, value));
  const restore = (field) => setResolved(restoreCompanyDefault(projectId, field));

  const handleZipBlur = async () => {
    const value = postalCode.trim();
    if (value !== "" && !ZIP_PATTERN.test(value)) {
      setZipError("Enter a five-digit ZIP code");
      return;
    }
    setZipError(null);
    if (value === savedPostalCode) return; // Unchanged -- nothing to save.

    setSaved({ state: "saving", at: Date.now() });
    try {
      const updated = await store.setPostalCode(projectId, value);
      const next = updated?.postalCode ?? "";
      setPostalCodeValue(next);
      setSavedPostalCode(next);
      setSaved({ state: "saved", at: Date.now() });
      showToast(next ? "Set project ZIP code" : "Cleared project ZIP code");
    } catch (err) {
      setSaved({ state: "error", at: Date.now() });
      setTimeout(() => setSaved((s) => (s?.state === "error" ? { state: "saved", at: Date.now() } : s)), 2600);
      setZipError(err?.message || "That change couldn't be saved. Try again.");
    }
  };

  if (state === "loading") return <p className="muted page">Loading project…</p>;

  if (state === "error") {
    return (
      <div className="page">
        <div className="load-error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" className="btn" onClick={load}>
            Try again
          </button>
        </div>
      </div>
    );
  }

  if (state !== "ready" || !project) {
    return (
      <div className="empty-state">
        <h1>That project isn't available</h1>
        <Link className="btn btn--primary" to="/projects">
          Back to projects
        </Link>
      </div>
    );
  }

  return (
    <>
      <AppTopBar
        title="Project settings"
        subtitle={project.name}
        breadcrumb={[
          { label: "Projects", to: "/projects" },
          { label: project.name, to: `/projects/${projectId}` },
        ]}
        saveState={saveStateText(saved)}
      />

      <div className="page">
        <h1 className="page-heading">Project settings</h1>

        <section className="card">
          <h2>Project details</h2>
          <dl className="detail-list">
            <dt>Project</dt>
            <dd>{project.name}</dd>
            <dt>Customer</dt>
            <dd>{project.customer || NOT_SET}</dd>
            <dt>Location</dt>
            <dd>{project.location || NOT_SET}</dd>
            <dt>
              <label className="formfield-label" htmlFor="proj-postal-code">
                ZIP code
              </label>
            </dt>
            <dd>
              <input
                id="proj-postal-code"
                className={zipError ? "field field--error" : "field"}
                inputMode="numeric"
                pattern="\d{5}"
                value={postalCode}
                onChange={(e) => {
                  setPostalCodeValue(e.target.value);
                  if (zipError) setZipError(null);
                }}
                onBlur={handleZipBlur}
                aria-describedby={zipError ? "proj-postal-code-error" : undefined}
                aria-invalid={zipError ? "true" : undefined}
              />
              {zipError ? (
                <p className="formfield-error" id="proj-postal-code-error">
                  {zipError}
                </p>
              ) : null}
            </dd>
            <dt>Internal number</dt>
            <dd className="tabular">{project.number || NOT_SET}</dd>
            <dt>Bid due</dt>
            <dd className="tabular">{formatCalendarDate(project.bidDueDate)}</dd>
            <dt>Active revision set</dt>
            <dd>{project.revisionSetLabel || NOT_SET}</dd>
          </dl>
        </section>

        <section className="card">
          <h2>Labor and pricing</h2>
          <p className="muted">
            These start from your company defaults. Change one to override it for this project only.
          </p>

          <div className="settings-list">
            {OVERRIDABLE.map((f) => {
              const entry = resolved[f.field];
              return (
                <div className="settings-row" key={f.field}>
                  <div className="settings-field">
                    <label className="formfield-label" htmlFor={`proj-${f.field}`}>
                      {f.label}
                    </label>
                    <div className="settings-input">
                      {f.prefix ? <span className="settings-affix">{f.prefix}</span> : null}
                      <input
                        id={`proj-${f.field}`}
                        className="field field--number tabular"
                        type="number"
                        step={f.step}
                        value={entry.value}
                        onChange={(e) => {
                          // Don't write an empty field as a 0 override --
                          // Number("") is 0, which would silently pin this
                          // project's rate to $0/hr. Only commit a real number.
                          const raw = e.target.value;
                          if (raw === "") return;
                          const n = Number(raw);
                          if (!Number.isNaN(n)) override(f.field, n);
                        }}
                      />
                      {f.suffix ? <span className="settings-affix">{f.suffix}</span> : null}
                    </div>
                  </div>
                  <div className="settings-source">
                    {/* Never colour alone: the source is stated in words, and
                        the override case adds an explicit restore control. */}
                    <span className={entry.overridden ? "pill pill--neutral" : "muted"}>{entry.source}</span>
                    {entry.overridden ? (
                      <button type="button" className="linkbtn" onClick={() => restore(f.field)}>
                        Restore company default ({f.prefix ?? ""}
                        {entry.companyValue}
                        {f.suffix ?? ""})
                      </button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section className="card">
          <h2>Audit history</h2>
          <p className="muted">
            Every approval, edit, and scale confirmation on this project is recorded in the review action log, with who
            did it and when.
          </p>
          <Link to={`/projects/${projectId}/takeoff`}>Open the review workspace</Link>
        </section>
      </div>

      {/* No Undo here, unlike the pricing screens' toast -- the ZIP PATCH
          is audited but not undoable (router.py's patch_postal_code
          docstring): a ZIP is settings, not a takeoff mutation. */}
      {toast ? (
        <div className="toast" role="status">
          {toast.text}
        </div>
      ) : null}
    </>
  );
}
