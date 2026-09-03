/* ============================================================
   EstimateDemo.jsx — the instant-estimate flow.

   Upload a drawing PDF, enter the project location, and get a priced
   Division 26 takeoff back from the engine (app/engine via the
   estimate service). Deliberately self-contained: it talks straight to
   the estimate service rather than the seed/api store, so the whole
   "blueprint in -> estimate out" loop works without the full backend.
   ============================================================ */

import { useRef, useState } from "react";
import { Upload, FileText, MapPin } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Pill from "../Pill.jsx";

// The standalone estimate service (see api/estimate_service.py).
const ESTIMATE_URL = "http://localhost:8100/estimate";

const money = (n) => "$" + Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });

export default function EstimateDemo() {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [location, setLocation] = useState("");
  const [state, setState] = useState("idle"); // idle | running | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const run = async () => {
    if (!file) return;
    setState("running");
    setError(null);
    try {
      const form = new FormData();
      form.append("location", location);
      form.append("file", file);
      const res = await fetch(ESTIMATE_URL, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "The estimate couldn't be produced.");
      setResult(data);
      setState("done");
    } catch (err) {
      setError(
        err.message === "Failed to fetch"
          ? "Couldn't reach the estimate service. Start it with: uvicorn estimate_service:app --port 8100"
          : err.message,
      );
      setState("error");
    }
  };

  const totals = result?.totals;

  return (
    <>
      <AppTopBar title="Instant estimate" />

      <div className="page">
        <h1 className="page-heading">Estimate from drawings</h1>
        <p className="muted">
          Upload an electrical drawing set and enter the project location. The takeoff and a location-priced total
          direct cost come back for you to review.
        </p>

        <div className="estimate-form card">
          <div className="formfield">
            <label className="formfield-label" htmlFor="est-location">
              <MapPin aria-hidden="true" size={14} /> Project location
            </label>
            <input
              id="est-location"
              className="field"
              type="text"
              value={location}
              placeholder="City, State (e.g. Unalaska, AK)"
              onChange={(e) => setLocation(e.target.value)}
            />
          </div>

          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files?.[0]) setFile(e.dataTransfer.files[0]);
            }}
          >
            <Upload aria-hidden="true" size={26} />
            {file ? (
              <p className="tabular">
                <FileText aria-hidden="true" size={14} /> {file.name}
              </p>
            ) : (
              <p>Drag a drawing PDF here</p>
            )}
            <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
              Choose file
            </button>
            <input
              ref={inputRef}
              type="file"
              accept="application/pdf"
              className="sr-only"
              onChange={(e) => {
                if (e.target.files?.[0]) setFile(e.target.files[0]);
                e.target.value = "";
              }}
            />
          </div>

          <button
            type="button"
            className="btn btn--primary"
            disabled={!file || state === "running"}
            onClick={run}
          >
            {state === "running" ? "Reading the drawings…" : "Estimate"}
          </button>
        </div>

        {state === "error" ? (
          <div className="load-error" role="alert">
            <p>{error}</p>
          </div>
        ) : null}

        {state === "running" ? (
          <p className="muted">Detecting sheets, counting devices, and pricing — this can take a moment.</p>
        ) : null}

        {state === "done" && result ? (
          <>
            <div className="estimate-summary card-grid">
              <section className="card estimate-headline">
                <h2>Total direct cost</h2>
                <p className="estimate-total tabular">{money(totals.total_direct_cost)}</p>
                <p className="muted">Material and labor only — markup, overhead, and profit are your layer.</p>
              </section>
              <section className="card">
                <h2>Basis</h2>
                <dl className="detail-list">
                  <dt>Location</dt>
                  <dd>{result.location || "National"}</dd>
                  <dt>Labor rate</dt>
                  <dd className="tabular">${result.labor_rate}/hr</dd>
                  <dt>Material factor</dt>
                  <dd className="tabular">{result.material_factor}×</dd>
                  <dt>Pricing</dt>
                  <dd>{result.source === "llm" ? "Automated (Claude)" : "Regional table"}</dd>
                </dl>
                <p className="muted">{result.location_note}</p>
                {/* Branch wiring is estimated per device rather than routed
                    off the drawing, and the basis card is where an
                    assumption behind the number belongs. */}
                {result.wiring_note ? <p className="muted">{result.wiring_note}</p> : null}
              </section>
              <section className="card">
                <h2>Coverage</h2>
                <dl className="detail-list">
                  <dt>Electrical sheets</dt>
                  <dd className="tabular">{result.sheets.length}</dd>
                  <dt>Line items</dt>
                  <dd className="tabular">{totals.item_count}</dd>
                  <dt>Need your review</dt>
                  <dd className="tabular">{totals.attention_count}</dd>
                  <dt>Labor</dt>
                  <dd className="tabular">{totals.labor_hours} hrs</dd>
                </dl>
              </section>
            </div>

            <div className="takeoff-table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    <th scope="col">Item</th>
                    <th scope="col">System</th>
                    <th scope="col">Qty</th>
                    <th scope="col">Sheets</th>
                    <th scope="col">Material</th>
                    <th scope="col">Labor hrs</th>
                    <th scope="col">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((r, i) => (
                    <tr key={i}>
                      <td>
                        <Pill status={r.status} />
                      </td>
                      <th scope="row">{r.name}</th>
                      <td>{r.system}</td>
                      <td className="tabular">
                        {r.quantity} {r.unit}
                      </td>
                      <td className="tabular">{r.sheets.join(", ")}</td>
                      <td className="tabular">{money(r.material_cost)}</td>
                      <td className="tabular">{r.labor_hours}</td>
                      <td className="tabular">{money(r.total_cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">
              Items marked <em>Needs attention</em> — mostly fixture types — need confirming against the luminaire
              schedule before they're approved. Unrecognized symbols are left unpriced rather than guessed.
            </p>
          </>
        ) : null}
      </div>
    </>
  );
}
