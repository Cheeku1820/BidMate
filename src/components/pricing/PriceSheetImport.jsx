/* ============================================================
   PriceSheetImport.jsx — the supplier price-sheet round trip's upload
   half (estimate-first-pricing §6, task 11). Download is a plain link
   in MaterialPricingWorkspace.jsx (store.priceRequestUrl); this modal
   is everything after the estimator has the filled sheet back:

     idle    -- a labelled file input, nothing uploaded yet
     reading -- uploaded; polling getPriceSheetPreview every 2s while
                the worker's price_sheet job is still queued/running
     ready   -- the worker's answer: three groups (matched / unmatched
                / unpriced) when the sheet parsed, or just the refusal
                reason when it didn't (refused sheets come back as
                state "ready" with matched: [] -- not a fourth state)

   Applying sends only the ticked matched rows -- unmatched/unpriced
   rows have nothing an apply could write. The apply itself is one
   commit() on the API side (kind "supplier_quote_apply", already in
   REVERSIBLE), so the undo toast the caller shows after onApplied()
   already has a real action behind it; nothing extra to wire here.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import Modal from "../Modal.jsx";
import { money, NONE } from "./pricingColumns.jsx";

const POLL_MS = 2000;

// The quote date the API requires, prefilled when the filename carried
// none: today, in the estimator's own calendar day (an ISO string from
// toISOString() is UTC, and after 5 pm in Sacramento that is tomorrow).
function todayIso() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// Same pattern as BulkApproveBar.jsx's per-status count (~line 76):
// only the digit itself gets `.tabular`, so the label text after it
// stays ordinary prose. The rendered textContent is unchanged from a
// plain string ("1 row matched", "Apply 2 prices"), so this is a
// presentational change only -- it doesn't touch what a test or a
// screen reader reads.
function CountLabel({ n, singular, plural }) {
  return (
    <>
      <span className="tabular">{n}</span> {n === 1 ? singular : plural}
    </>
  );
}

export default function PriceSheetImport({ projectId, store, onApplied, onClose }) {
  const [phase, setPhase] = useState("idle"); // idle | reading | ready | failed
  const [documentId, setDocumentId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [ticked, setTicked] = useState(() => new Set());
  const [supplierName, setSupplierName] = useState("");
  const [quoteDate, setQuoteDate] = useState("");
  const [saveToCompany, setSaveToCompany] = useState(false);
  const [applying, setApplying] = useState(false);

  // Polling has to stop cleanly on unmount -- closing the modal mid-poll
  // must not schedule a setState against a component that is gone.
  const cancelledRef = useRef(false);
  const timeoutRef = useRef(null);
  useEffect(
    () => () => {
      cancelledRef.current = true;
      clearTimeout(timeoutRef.current);
    },
    [],
  );

  function pollPreview(docId) {
    async function tick() {
      let result;
      try {
        result = await store.getPriceSheetPreview(projectId, docId);
      } catch (err) {
        if (cancelledRef.current) return;
        setError(err?.message || "Couldn't read the price sheet preview. Try again.");
        setPhase("failed");
        return;
      }
      if (cancelledRef.current) return;
      if (result.state === "reading") {
        timeoutRef.current = setTimeout(tick, POLL_MS);
        return;
      }
      setPreview(result);
      setPhase(result.state);
      if (result.state === "ready") {
        setSupplierName(result.supplierName || "");
        setQuoteDate(result.quoteDate || todayIso());
        setTicked(new Set(result.matched.map((m) => m.itemId)));
      } else if (result.state === "failed") {
        setError(result.error || "The price sheet couldn't be read. Try again.");
      }
    }
    tick();
  }

  async function handleFile(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    setPhase("reading");
    try {
      const { documentId: docId } = await store.uploadPriceSheet(projectId, file);
      setDocumentId(docId);
      pollPreview(docId);
    } catch (err) {
      setError(err?.message || "Couldn't upload the price sheet. Try again.");
      setPhase("idle");
    }
  }

  function toggle(itemId) {
    setTicked((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  async function handleApply() {
    setError(null);
    setApplying(true);
    const itemIds = Array.from(ticked);
    try {
      const result = await store.applyPriceSheet(projectId, documentId, {
        itemIds,
        supplierName: supplierName.trim(),
        quoteDate,
        saveToCompany,
      });
      onApplied(result, itemIds.length);
    } catch (err) {
      setError(err?.message || "That price sheet couldn't be applied. Try again.");
      setApplying(false);
    }
  }

  const ready = phase === "ready" && preview && !preview.refused;
  // The API refuses an apply without a supplier and a quote date, so
  // the button waits for both rather than sending a request it knows
  // will come back 422.
  const canApply = ready && ticked.size > 0 && supplierName.trim().length > 0 && quoteDate.length > 0 && !applying;

  return (
    <Modal
      title="Upload supplier pricing"
      onClose={onClose}
      foot={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          {ready ? (
            <button type="button" className="btn btn--primary" onClick={handleApply} disabled={!canApply}>
              {applying ? (
                "Applying…"
              ) : (
                <>
                  Apply <span className="tabular">{ticked.size}</span> price{ticked.size === 1 ? "" : "s"}
                </>
              )}
            </button>
          ) : null}
        </>
      }
    >
      {error ? (
        <div className="warncard warncard--missing" role="alert">
          <p>{error}</p>
        </div>
      ) : null}

      {phase === "idle" ? (
        <div className="formfield">
          <label className="formfield-label" htmlFor="price-sheet-file">
            Price sheet
          </label>
          <p className="formfield-hint" id="price-sheet-file-hint">
            Upload the .xlsx or .csv your supplier filled in. Start from Download price request so rows match
            exactly.
          </p>
          <input
            id="price-sheet-file"
            className="field"
            type="file"
            accept=".xlsx,.csv"
            onChange={handleFile}
            aria-describedby="price-sheet-file-hint"
          />
        </div>
      ) : null}

      {phase === "reading" ? <p className="muted">Reading the price sheet…</p> : null}

      {phase === "ready" && preview?.refused ? (
        <div className="warncard warncard--missing" role="alert">
          <p>{preview.refused}</p>
        </div>
      ) : null}

      {ready ? (
        <>
          {preview.matched.length > 0 ? (
            <div className="pricesheet-group">
              <h4><CountLabel n={preview.matched.length} singular="row matched" plural="rows matched" /></h4>
              <ul className="pricesheet-rows">
                {preview.matched.map((row) => (
                  <li key={row.itemId} className="pricesheet-row">
                    <label className="pricesheet-row__check">
                      <input type="checkbox" checked={ticked.has(row.itemId)} onChange={() => toggle(row.itemId)} />
                      {row.itemName}
                    </label>
                    <span className="pricesheet-row__prices">
                      <span className="tabular">{row.currentUnitPrice != null ? money(row.currentUnitPrice) : NONE}</span>
                      {row.currentSourceLabel ? <span className="muted"> {row.currentSourceLabel}</span> : null}
                      <span aria-hidden="true"> → </span>
                      <span className="tabular">{money(row.newUnitPrice)}</span>
                    </span>
                    {row.partNo ? <span className="muted">{row.partNo}</span> : null}
                    {row.notes ? <span className="muted">{row.notes}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {preview.unmatched.length > 0 ? (
            <div className="pricesheet-group">
              <h4><CountLabel n={preview.unmatched.length} singular="row not on this project" plural="rows not on this project" /></h4>
              <ul className="pricesheet-plainlist">
                {preview.unmatched.map((row, i) => (
                  <li key={i}>
                    {row.itemName} <span className="tabular muted">{row.unitPrice != null ? money(row.unitPrice) : NONE}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {preview.unpriced.length > 0 ? (
            <div className="pricesheet-group">
              <h4><CountLabel n={preview.unpriced.length} singular="item left unpriced" plural="items left unpriced" /></h4>
              <ul className="pricesheet-plainlist">
                {preview.unpriced.map((row) => (
                  <li key={row.itemId}>{row.itemName}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="formfield">
            <label className="formfield-label" htmlFor="price-sheet-supplier">
              Supplier
            </label>
            <input
              id="price-sheet-supplier"
              className="field"
              type="text"
              value={supplierName}
              onChange={(e) => setSupplierName(e.target.value)}
            />
          </div>

          <div className="formfield">
            <label className="formfield-label" htmlFor="price-sheet-date">
              Quote date
            </label>
            <input
              id="price-sheet-date"
              className="field"
              type="date"
              value={quoteDate || ""}
              onChange={(e) => setQuoteDate(e.target.value)}
            />
          </div>

          <label className="switch">
            <input type="checkbox" checked={saveToCompany} onChange={(e) => setSaveToCompany(e.target.checked)} />
            Also save these to the company price book
          </label>
        </>
      ) : null}
    </Modal>
  );
}
