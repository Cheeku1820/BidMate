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

import { useMemo } from "react";
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
  const { snapshot, loading, loadError, refresh, projectId, project } = useWorkspaceContext();

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
    const blob = new Blob([toCsv(exportRows)], { type: "text/csv;charset=utf-8" });
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
