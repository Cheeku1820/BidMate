/* ============================================================
   ExportPreview.jsx — spec §5 screen H, "confirm exactly what will
   leave the platform".

   Reads the one shared store subscription through useWorkspaceContext(),
   so the approved totals here are the SAME numbers the bottom drawer and
   screen G show -- computed once, in the store's computeTotals()
   (invariant 1), never re-summed here. Re-summing would be a second
   implementation of the same total that could drift from the drawer the
   estimator just trusted.

   Two rules from the finish-review gate carry here, because the export
   nav item can be reached directly rather than only through the modal:
   Missing information blocks export with no override (a link back to the
   blocking items, no "export anyway"), and Needs attention items export
   only as acknowledged allowances. Rejected items are excluded scope --
   named as such, never silently dropped.
   ============================================================ */

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { countsTowardTotals } from "../../lib/rules.js";

// The columns the workbook carries, in order. Kept as data so the
// on-screen preview header and the generated file can never list
// different columns.
const EXPORT_COLUMNS = ["Item", "Description", "System", "Quantity", "Unit", "Sheet", "Status", "Material", "Labor hrs", "Total"];

const STATUS_TEXT = {
  approved: "Estimator approved",
  attention: "Allowance (needs attention)",
};

function sanitizeFileName(name) {
  return (name || "takeoff").trim().replace(/[^a-z0-9]+/gi, "-").replace(/^-+|-+$/g, "").toLowerCase() || "takeoff";
}

function toCsv(rows) {
  const escape = (v) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [EXPORT_COLUMNS, ...rows].map((row) => row.map(escape).join(",")).join("\r\n");
}

export default function ExportPreview() {
  const { snapshot, loading, loadError, refresh, projectId, project, store } = useWorkspaceContext();

  // The schedule, for the phase roll-up and the long-lead section. It
  // is a separate read because the export is a view onto the same
  // approved totals whether or not a project is phased: a single-phase
  // bid exports exactly as it did before, plus its general-conditions
  // lines and any long-lead rows.
  const [schedule, setSchedule] = useState(null);
  useEffect(() => {
    if (typeof store?.getSchedule !== "function") return undefined;
    let alive = true;
    store
      .getSchedule(projectId)
      .then((next) => {
        if (alive) setSchedule(next);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [store, projectId]);

  const items = snapshot?.items ?? [];
  const sheets = snapshot?.sheets ?? [];
  const totals = snapshot?.totals;

  const sheetsById = useMemo(() => {
    const map = {};
    for (const sheet of sheets) map[sheet.id] = sheet;
    return map;
  }, [sheets]);

  // The by-system quantities read straight from the store's totals
  // (invariant 1). These per-status buckets go through the same
  // countsTowardTotals predicate the store's own totals use, rather than
  // a hand-rolled `!rejected` filter -- so an item on a superseded sheet
  // is excluded here exactly as it is from the totals, not left able to
  // block the export while contributing nothing to it.
  const countable = items.filter((i) => countsTowardTotals(i, sheetsById));
  const approved = countable.filter((i) => i.status === "approved");
  const allowances = countable.filter((i) => i.status === "attention");
  const blocking = countable.filter((i) => i.status === "missing");
  const rejected = items.filter((i) => i.rejected);

  const bySystem = totals?.bySystem ?? {};
  const systems = Object.keys(bySystem).sort();

  const fileName = `${sanitizeFileName(project?.name)}-takeoff.csv`;

  const exportRows = [...approved, ...allowances].map((item) => [
    item.name,
    item.description ?? "",
    item.system ?? "",
    item.quantity ?? "",
    item.unit ?? "",
    sheetsById[item.sheetId]?.number ?? "",
    STATUS_TEXT[item.status] ?? item.status,
    item.materialCost ? Math.round(item.materialCost) : "",
    item.laborHours ? item.laborHours : "",
    item.totalCost ? Math.round(item.totalCost) : "",
  ]);

  // The phase roll-up: one lump-sum line per phase carrying its hours
  // and material, exactly as the firm's own summary sheet does, then
  // each phase's own section below it. A single-phase project gets no
  // summary block — there is nothing to roll up.
  const phases = schedule?.phases ?? [];
  const multiPhase = Boolean(schedule?.multiPhase);
  const phaseOf = (item) => item.phaseId ?? phases[0]?.id ?? null;

  const summaryRows = multiPhase
    ? phases.map((phase) => [
        phase.name, "", "", 1, "LS", "", "Phase total",
        phase.materialTotal ? Math.round(phase.materialTotal) : "",
        Number((phase.directHours + phase.generalConditionsHours).toFixed(2)),
        "",
      ])
    : [];

  const generalConditionsRows = phases.flatMap((phase) =>
    phase.lines.map((line) => [
      line.label, multiPhase ? phase.name : "", "General conditions", 1, "LS", "", "",
      "", Number(line.hours.toFixed(2)), "",
    ]),
  );

  const sectionedRows = multiPhase
    ? phases.flatMap((phase) => [
        [`— ${phase.name} —`, "", "", "", "", "", "", "", "", ""],
        ...phase.lines.map((line) => [
          line.label, "", "General conditions", 1, "LS", "", "", "", Number(line.hours.toFixed(2)), "",
        ]),
        ...exportRows.filter((_, index) => phaseOf([...approved, ...allowances][index]) === phase.id),
      ])
    : [...generalConditionsRows, ...exportRows];

  const leadRows = (schedule?.leads ?? []).map((lead) => [
    lead.itemName,
    multiPhase ? lead.phaseName : "",
    "Long-lead item",
    lead.leadWeeks ?? "",
    lead.leadWeeks == null ? "" : "weeks",
    lead.sourceLabel || "",
    lead.leadWeeks == null ? "Not yet quoted" : `Needed for ${lead.neededForStage.replace("_", " ")}`,
    "", "", lead.orderBy ?? "",
  ]);

  const csvRows = schedule === null ? exportRows : [...summaryRows, ...sectionedRows, ...leadRows];

  // Estimate cost over the whole takeoff. An unpriced takeoff carries
  // zero on every item, and zero is not a price -- the card stays hidden
  // rather than exporting a confident $0.
  const cost = (list, field) => list.reduce((sum, i) => sum + (i[field] || 0), 0);
  const hasCost = countable.some((i) => i.totalCost > 0);
  const materialTotal = cost(countable, "materialCost");
  const laborHoursTotal = cost(countable, "laborHours");
  const laborCostTotal = cost(countable, "laborCost");
  const directTotal = cost(countable, "totalCost");
  const dollars = (n) => "$" + Math.round(n).toLocaleString();

  const onExport = () => {
    // A client-side download of the estimator's own approved takeoff.
    // Excel opens CSV natively; a production build would emit a real
    // .xlsx workbook, which needs a library this prototype deliberately
    // does not pull in -- the reconciliation guarantee (these totals
    // equal the drawer's) is the part that matters and is real here.
    const blob = new Blob([toCsv(csvRows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <AppTopBar
        title="Export"
        primaryAction={
          <button type="button" className="btn btn--primary" disabled={blocking.length > 0 || approved.length === 0} onClick={onExport}>
            Export Excel
          </button>
        }
      />

      <div className="page">
        <h1 className="page-heading">Export preview</h1>

        {loading ? <p className="muted">Loading takeoff…</p> : null}
        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={refresh}>
              Try again
            </button>
          </div>
        ) : null}

        {!loading && !loadError ? (
          <>
            {blocking.length > 0 ? (
              <div className="warncard warncard--missing" role="alert">
                <h4>Missing information blocks export</h4>
                <p>
                  {blocking.length} {blocking.length === 1 ? "item is" : "items are"} missing required information and
                  must be resolved before this takeoff can be exported. There is no override.
                </p>
                <Link className="linkbtn" to={`/projects/${projectId}/takeoff`}>
                  Go to the review workspace
                </Link>
              </div>
            ) : null}

            <div className="card-grid">
              <section className="card">
                <h2>Project</h2>
                <dl className="detail-list">
                  <dt>Project</dt>
                  <dd>{project?.name ?? "This project"}</dd>
                  <dt>Revision set</dt>
                  <dd>{project?.revisionSetLabel || "—"}</dd>
                  {project?.location ? (
                    <>
                      <dt>Location</dt>
                      <dd>{project.location}</dd>
                    </>
                  ) : null}
                  <dt>File name</dt>
                  <dd className="tabular">{fileName}</dd>
                </dl>
              </section>

              {hasCost ? (
                <section className="card estimate-headline">
                  <h2>Estimated total direct cost</h2>
                  <p className="estimate-total tabular">{dollars(directTotal)}</p>
                  <dl className="detail-list">
                    <dt>Material</dt>
                    <dd className="tabular">{dollars(materialTotal)}</dd>
                    <dt>Labor</dt>
                    <dd className="tabular">
                      {Math.round(laborHoursTotal)} hrs{project?.laborRate ? ` @ $${project.laborRate}/hr` : ""} ·{" "}
                      {dollars(laborCostTotal)}
                    </dd>
                  </dl>
                  <p className="muted">
                    Material and labor only — markup, overhead, and profit are your layer.
                    {project?.pricingSource === "llm" ? " Priced automatically for the location." : ""}
                  </p>
                  {/* The basis these totals rest on -- the location index,
                      and that branch wiring was estimated per device
                      rather than routed off the drawing. It belongs here
                      most of all: this is the number that leaves the
                      building, and an assumption nobody is shown is one
                      nobody can check. */}
                  {project?.pricingNote ? <p className="muted">{project.pricingNote}</p> : null}
                </section>
              ) : null}

              <section className="card">
                <h2>Approved totals by system</h2>
                {systems.length === 0 ? (
                  <p className="muted">No approved items yet.</p>
                ) : (
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th scope="col">System</th>
                        <th scope="col">Approved quantity</th>
                      </tr>
                    </thead>
                    <tbody>
                      {systems.map((system) => (
                        <tr key={system}>
                          <th scope="row">{system}</th>
                          <td className="tabular">{bySystem[system]}</td>
                        </tr>
                      ))}
                      <tr>
                        <th scope="row">All systems</th>
                        <td className="tabular">{totals?.approvedUnits ?? 0}</td>
                      </tr>
                    </tbody>
                  </table>
                )}
              </section>

              <section className="card">
                <h2>Scope</h2>
                <dl className="detail-list">
                  <dt>Approved items</dt>
                  <dd className="tabular">{approved.length}</dd>
                  <dt>Acknowledged allowances</dt>
                  <dd className="tabular">{allowances.length}</dd>
                  <dt>Excluded (rejected)</dt>
                  <dd className="tabular">{rejected.length}</dd>
                </dl>
              </section>
            </div>

            {multiPhase ? (
              <section className="card">
                <h2>Summary by phase</h2>
                <p className="muted">
                  Each phase exports as one lump-sum line carrying its hours, the way the firm's summary sheet does.
                </p>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Phase</th>
                      <th scope="col">Qty</th>
                      <th scope="col">Unit</th>
                      <th scope="col">Labor hours</th>
                      <th scope="col">Material</th>
                    </tr>
                  </thead>
                  <tbody>
                    {phases.map((phase) => (
                      <tr key={phase.id}>
                        <td>{phase.name}</td>
                        <td className="tabular">1</td>
                        <td>LS</td>
                        <td className="tabular">
                          {(phase.directHours + phase.generalConditionsHours).toFixed(2)}
                        </td>
                        <td className="tabular">{phase.materialTotal ? dollars(phase.materialTotal) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ) : null}

            {leadRows.length ? (
              <section className="card">
                <h2>Long-lead items</h2>
                <p className="muted">
                  Stated in the bid so the lead times are on the record. A row with no quote says so rather than
                  carrying a date nobody gave.
                </p>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Item</th>
                      {multiPhase ? <th scope="col">Phase</th> : null}
                      <th scope="col">Lead weeks</th>
                      <th scope="col">Source</th>
                      <th scope="col">Needed for</th>
                      <th scope="col">Order by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(schedule?.leads ?? []).map((lead) => (
                      <tr key={lead.itemId}>
                        <td>{lead.itemName}</td>
                        {multiPhase ? <td>{lead.phaseName}</td> : null}
                        <td className="tabular">{lead.leadWeeks ?? "Not yet quoted"}</td>
                        <td>{lead.sourceLabel || "—"}</td>
                        <td>{lead.neededForStage.replace("_", " ")}</td>
                        <td className="tabular">{lead.orderBy ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            ) : null}

            <section className="card">
              <h2>Columns in the export</h2>
              <div className="takeoff-table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      {EXPORT_COLUMNS.map((col) => (
                        <th key={col} scope="col">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {exportRows.slice(0, 5).map((row, idx) => (
                      <tr key={idx}>
                        {row.map((cell, cellIdx) => (
                          <td key={cellIdx} className={cellIdx === 3 ? "tabular" : undefined}>
                            {cell}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {exportRows.length > 5 ? (
                <p className="muted tabular">Showing 5 of {exportRows.length} rows.</p>
              ) : null}
            </section>

            <div className="form-actions">
              <button type="button" className="btn btn--primary" disabled={blocking.length > 0 || approved.length === 0} onClick={onExport}>
                Export Excel
              </button>
              <Link className="btn" to={`/projects/${projectId}/takeoff`}>
                Return to review
              </Link>
            </div>
          </>
        ) : null}
      </div>
    </>
  );
}
