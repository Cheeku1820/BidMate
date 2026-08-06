import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import {
  ArrowLeft, Search, Undo2, Redo2, HelpCircle, ChevronUp, ChevronDown,
  ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Maximize2, Hand, Ruler,
  Layers, BookOpen, X, Check, Pencil, Trash2, CircleSlash, FileText,
  AlertTriangle, AlertCircle, CheckCircle2, Circle, ExternalLink,
} from "lucide-react";
import BlueprintCanvas from "./components/BlueprintCanvas.jsx";
import { SymbolGlyph, SYMBOL_LABELS } from "./components/Symbols.jsx";
import { SHEETS, ITEMS, STATUS, STATUS_ORDER, SYSTEMS } from "./lib/data.js";
import { read, write, subscribe, listKeys, removeKey, identity, initials } from "./lib/sync.js";

const STATUS_ICON = { ready: Circle, attention: AlertTriangle, missing: AlertCircle, approved: CheckCircle2, rejected: CircleSlash };

function Pill({ status }) {
  const Icon = STATUS_ICON[status];
  return (
    <span className={"pill pill--" + status}>
      <Icon size={12} strokeWidth={2.6} />
      {STATUS[status].label}
    </span>
  );
}

function timeOf(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

const uid = (p) => p + "_" + Math.random().toString(36).slice(2, 9);

export default function App() {
  const me = useMemo(identity, []);

  const [items, setItems] = useState(() => read("items", ITEMS));
  const [sheets, setSheets] = useState(() => read("sheets", SHEETS));
  const [hist, setHist] = useState(() => read("hist", { undo: [], redo: [] }));
  const [peers, setPeers] = useState([]);
  const [saved, setSaved] = useState({ state: "saved", at: Date.now() });

  const [sheetId, setSheetId] = useState("E2.1");
  const [selId, setSelId] = useState(null);
  const [filter, setFilter] = useState("all");
  const [sheetQuery, setSheetQuery] = useState("");
  const [railOpen, setRailOpen] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [tool, setTool] = useState("pan");
  const [canvasQuery, setCanvasQuery] = useState("");
  const [showFind, setShowFind] = useState(false);
  const [layers, setLayers] = useState({ detected: true, approved: true, rejected: false, measurements: true, warnings: true, legend: true });
  const [menu, setMenu] = useState(null);
  const [modal, setModal] = useState(null);
  const [edit, setEdit] = useState(null);
  const [ack, setAck] = useState(false);
  const [toast, setToast] = useState(null);
  const localWrite = useRef(0);

  const sheet = sheets.find((s) => s.id === sheetId) || sheets[0];
  const sel = items.find((i) => i.id === selId) || null;

  /* ---------------------------------------------- sync */

  const persist = useCallback((nextItems, nextSheets, nextHist) => {
    localWrite.current = Date.now();
    setSaved({ state: "saving", at: Date.now() });
    const ok = write("items", nextItems) && write("sheets", nextSheets) && write("hist", nextHist);
    setTimeout(() => setSaved({ state: ok ? "saved" : "error", at: Date.now() }), 220);
  }, []);

  useEffect(() => {
    const beat = () => write("presence:" + me.id, { ...me, at: Date.now(), sheetId, itemId: selId });
    beat();
    const iv = setInterval(beat, 4000);
    const bye = () => removeKey("presence:" + me.id);
    window.addEventListener("beforeunload", bye);
    return () => {
      clearInterval(iv);
      window.removeEventListener("beforeunload", bye);
    };
  }, [me, sheetId, selId]);

  useEffect(() => {
    const refresh = () => {
      const now = Date.now();
      setPeers(listKeys("presence:").map((k) => read(k, null)).filter((p) => p && now - p.at < 14000));
      if (now - localWrite.current > 400) {
        setItems(read("items", ITEMS));
        setSheets(read("sheets", SHEETS));
        setHist(read("hist", { undo: [], redo: [] }));
      }
    };
    refresh();
    const off = subscribe(refresh);
    const iv = setInterval(refresh, 3000);
    return () => {
      off();
      clearInterval(iv);
    };
  }, []);

  const others = peers.filter((p) => p.id !== me.id);
  const remoteSelections = others.filter((p) => p.sheetId === sheetId && p.itemId).map((p) => ({ itemId: p.itemId, color: p.color, name: p.name }));

  /* ---------------------------------------------- actions */

  function commit(action, nextItems, nextSheets = sheets) {
    const nextHist = { undo: [...hist.undo, action].slice(-60), redo: [] };
    setItems(nextItems);
    setSheets(nextSheets);
    setHist(nextHist);
    persist(nextItems, nextSheets, nextHist);
    setToast({ id: action.id, text: action.label });
    setTimeout(() => setToast((t) => (t && t.id === action.id ? null : t)), 5000);
  }

  function setStatus(id, status) {
    const it = items.find((i) => i.id === id);
    if (!it) return;
    const clears = status === "approved";
    const before = { status: it.status, warning: it.warning, approvedBy: it.approvedBy };
    const after = { status, warning: clears ? null : it.warning, approvedBy: clears ? me.name : undefined };
    const next = items.map((i) => (i.id === id ? { ...i, ...after } : i));
    const verb = status === "approved" ? "Approved" : status === "rejected" ? "Rejected" : "Updated";
    commit({ id: uid("a"), kind: "status", itemId: id, before, after, by: me.name, at: Date.now(), label: `${verb} ${it.name}` }, next);
  }

  function saveEdit() {
    const it = items.find((i) => i.id === selId);
    if (!it || !edit) return;
    const before = { system: it.system, category: it.category, quantity: it.quantity, notes: it.notes, symbol: it.symbol, status: it.status };
    const nextStatus = it.status === "attention" && it.category === "Unclassified" && edit.category !== "Unclassified" ? "ready" : it.status;
    const after = {
      system: edit.system,
      category: edit.category,
      quantity: Number(edit.quantity) || 0,
      notes: edit.notes,
      symbol: edit.symbol,
      status: nextStatus,
    };
    const next = items.map((i) => (i.id === it.id ? { ...i, ...after } : i));
    commit({ id: uid("a"), kind: "edit", itemId: it.id, before, after, by: me.name, at: Date.now(), label: `Edited ${it.name}` }, next);
    setEdit(null);
  }

  function removeItem(id) {
    const idx = items.findIndex((i) => i.id === id);
    const it = items[idx];
    const next = items.filter((i) => i.id !== id);
    if (selId === id) setSelId(null);
    commit({ id: uid("a"), kind: "delete", itemId: id, index: idx, snapshot: it, by: me.name, at: Date.now(), label: `Deleted ${it.name}` }, next);
    setModal(null);
  }

  function applyScale(value) {
    const affected = items.filter((i) => i.sheetId === sheet.id && i.status === "missing");
    const before = { scale: sheet.scale, items: affected.map((i) => ({ id: i.id, status: i.status, warning: i.warning })) };
    const after = { scale: value, items: affected.map((i) => ({ id: i.id, status: "ready", warning: null })) };
    const ids = new Set(affected.map((i) => i.id));
    const nextItems = items.map((i) => (ids.has(i.id) ? { ...i, status: "ready", warning: null } : i));
    const nextSheets = sheets.map((s) => (s.id === sheet.id ? { ...s, scale: value } : s));
    commit(
      { id: uid("a"), kind: "scale", sheetId: sheet.id, before, after, by: me.name, at: Date.now(), label: `Set scale on ${sheet.number} — ${affected.length} measured items recalculated` },
      nextItems,
      nextSheets
    );
    setModal(null);
    setTool("pan");
  }

  function undo() {
    if (!hist.undo.length) return;
    const a = hist.undo[hist.undo.length - 1];
    let nItems = items;
    let nSheets = sheets;
    if (a.kind === "status" || a.kind === "edit") nItems = items.map((i) => (i.id === a.itemId ? { ...i, ...a.before } : i));
    if (a.kind === "delete") {
      nItems = items.slice();
      nItems.splice(a.index, 0, a.snapshot);
    }
    if (a.kind === "scale") {
      nSheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.before.scale } : s));
      const m = Object.fromEntries(a.before.items.map((x) => [x.id, x]));
      nItems = items.map((i) => (m[i.id] ? { ...i, status: m[i.id].status, warning: m[i.id].warning } : i));
    }
    const nHist = { undo: hist.undo.slice(0, -1), redo: [...hist.redo, a] };
    setItems(nItems);
    setSheets(nSheets);
    setHist(nHist);
    persist(nItems, nSheets, nHist);
  }

  function redo() {
    if (!hist.redo.length) return;
    const a = hist.redo[hist.redo.length - 1];
    let nItems = items;
    let nSheets = sheets;
    if (a.kind === "status" || a.kind === "edit") nItems = items.map((i) => (i.id === a.itemId ? { ...i, ...a.after } : i));
    if (a.kind === "delete") nItems = items.filter((i) => i.id !== a.itemId);
    if (a.kind === "scale") {
      nSheets = sheets.map((s) => (s.id === a.sheetId ? { ...s, scale: a.after.scale } : s));
      const m = Object.fromEntries(a.after.items.map((x) => [x.id, x]));
      nItems = items.map((i) => (m[i.id] ? { ...i, status: m[i.id].status, warning: m[i.id].warning } : i));
    }
    const nHist = { undo: [...hist.undo, a], redo: hist.redo.slice(0, -1) };
    setItems(nItems);
    setSheets(nSheets);
    setHist(nHist);
    persist(nItems, nSheets, nHist);
  }

  function select(id) {
    const it = items.find((i) => i.id === id);
    if (it) setSheetId(it.sheetId);
    setSelId(id);
    setEdit(null);
  }

  function step(dir) {
    const list = items.filter((i) => i.sheetId === sheetId);
    if (!list.length) return;
    const i = list.findIndex((x) => x.id === selId);
    select(list[i === -1 ? 0 : (i + dir + list.length) % list.length].id);
  }

  function nextIssue() {
    const it = items.find((i) => i.status === "missing") || items.find((i) => i.status === "attention");
    if (it) select(it.id);
  }

  const canvasCmd = (type) => window.dispatchEvent(new CustomEvent("canvas-cmd", { detail: { type } }));

  useEffect(() => {
    const openScale = () => setModal({ kind: "scale" });
    window.addEventListener("open-scale", openScale);
    return () => window.removeEventListener("open-scale", openScale);
  }, []);

  useEffect(() => {
    function onKey(e) {
      const t = document.activeElement;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey) return;
      if (e.key === "Escape") { setModal(null); setMenu(null); setEdit(null); return; }
      if (e.key === "a" && sel) setStatus(sel.id, "approved");
      else if (e.key === "e" && sel) setEdit({ system: sel.system, category: sel.category, quantity: sel.quantity, notes: sel.notes || "", symbol: sel.symbol });
      else if (e.key === "r" && sel) setStatus(sel.id, "rejected");
      else if (e.key === "j") step(1);
      else if (e.key === "k") step(-1);
      else if (e.key === "+" || e.key === "=") canvasCmd("in");
      else if (e.key === "-") canvasCmd("out");
      else if (e.key === "0") canvasCmd("fit");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /* ---------------------------------------------- derived */

  const counts = STATUS_ORDER.reduce((acc, k) => ({ ...acc, [k]: items.filter((i) => i.status === k).length }), {});
  const approvedQty = items.filter((i) => i.status === "approved").reduce((s, i) => s + i.quantity, 0);
  const overall = counts.missing ? "missing" : counts.attention ? "attention" : counts.ready ? "ready" : "approved";
  const blocking = items.filter((i) => i.status === "missing");
  const soft = items.filter((i) => i.status === "attention");

  const bySystem = SYSTEMS.map((s) => {
    const list = items.filter((i) => i.system === s);
    return { system: s, approved: list.filter((i) => i.status === "approved").length, total: list.length };
  }).filter((r) => r.total);

  const sheetsShown = sheets.filter((s) => {
    if (sheetQuery && !(s.number + " " + s.title).toLowerCase().includes(sheetQuery.toLowerCase())) return false;
    const its = items.filter((i) => i.sheetId === s.id);
    if (filter === "electrical") return s.discipline === "Electrical";
    if (filter === "attention") return its.some((i) => i.status === "attention" || i.status === "missing");
    if (filter === "reviewed") return its.length > 0 && its.every((i) => i.status === "approved" || i.status === "rejected");
    return true;
  });

  return (
    <div className="app">
      <p className="too-narrow">Use a larger screen to review drawings. This workspace needs at least 1024px of width.</p>

      {/* ---------------------------------------- top bar */}
      <header className="topbar">
        <button className="iconbtn"><ArrowLeft size={16} /> Projects</button>
        <div className="topbar__rule" />
        <div className="topbar__title">
          <strong>Meridian Distribution Center — Division 26</strong>
          <span>Active set: E1.1 Rev 3 · E2.1 Rev 2 · E3.1 Rev 1</span>
        </div>
        <Pill status={overall} />
        <span className="savestate tabular">
          {saved.state === "saving" ? "Saving…" : saved.state === "error" ? "Couldn't save — retrying" : "Saved " + timeOf(saved.at)}
        </span>
        <div className="spacer" />
        <div className="presence">
          {[me, ...others].slice(0, 5).map((p) => (
            <span key={p.id} className="avatar" style={{ background: p.color }} title={p.name + (p.id === me.id ? " (you)" : "")}>
              {initials(p.name)}
            </span>
          ))}
        </div>
        <div className="topbar__rule" />
        <button className="iconbtn" onClick={undo} disabled={!hist.undo.length} title={hist.undo.length ? "Undo: " + hist.undo[hist.undo.length - 1].label : "Nothing to undo"}>
          <Undo2 size={16} />
        </button>
        <button className="iconbtn" onClick={redo} disabled={!hist.redo.length} title="Redo">
          <Redo2 size={16} />
        </button>
        <button className="iconbtn" onClick={() => setModal({ kind: "help" })}><HelpCircle size={16} /></button>
        <button className="btn btn--primary" onClick={() => setModal({ kind: "finish" })}>Finish review</button>
      </header>

      <div className="workspace">
        {/* -------------------------------------- sheets rail */}
        <nav className={"sheets" + (railOpen ? "" : " sheets--collapsed")} aria-label="Sheets">
          {railOpen && (
            <>
              <div className="sheets__head">
                <div className="search">
                  <Search size={14} color="var(--ink-3)" />
                  <input value={sheetQuery} onChange={(e) => setSheetQuery(e.target.value)} placeholder="Search sheets" aria-label="Search sheets" />
                </div>
              </div>
              <div className="chips">
                {[["all", "All"], ["electrical", "Electrical"], ["attention", "Needs attention"], ["reviewed", "Reviewed"]].map(([k, l]) => (
                  <button key={k} className="chip" aria-pressed={filter === k} onClick={() => setFilter(k)}>{l}</button>
                ))}
              </div>
              <div className="sheetlist">
                {sheetsShown.map((s) => {
                  const its = items.filter((i) => i.sheetId === s.id);
                  const warn = its.filter((i) => i.warning).length;
                  const done = its.length > 0 && its.every((i) => i.status === "approved" || i.status === "rejected");
                  return (
                    <button key={s.id} className="sheetrow" aria-current={s.id === sheetId} onClick={() => setSheetId(s.id)}>
                      <span className="sheetrow__thumb">
                        <svg viewBox="0 0 1000 750" width="100%" height="100%">
                          <rect x="80" y="80" width="840" height="520" fill="none" stroke="#c2beb4" strokeWidth="26" />
                          {its.slice(0, 6).map((i) => (
                            <circle key={i.id} cx={i.path ? i.path[0][0] : i.x} cy={i.path ? i.path[0][1] : i.y} r="34" fill={STATUS[i.status].color} />
                          ))}
                        </svg>
                      </span>
                      <span className="sheetrow__meta">
                        <strong>{s.number}</strong>
                        <p>{s.title}</p>
                        <span className="badges">
                          <span className="badge">{s.revision}</span>
                          {warn > 0 && <span className="badge badge--warn">{warn} warning{warn > 1 ? "s" : ""}</span>}
                          {done && <span className="badge badge--done"><Check size={10} /> Reviewed</span>}
                        </span>
                      </span>
                    </button>
                  );
                })}
                {!sheetsShown.length && <p style={{ padding: 16, fontSize: 13, color: "var(--ink-3)" }}>No sheets match that search. Clear the search to see all sheets.</p>}
              </div>
            </>
          )}
          <div className="rail-foot">
            <button className="iconbtn" onClick={() => setRailOpen((v) => !v)} aria-label={railOpen ? "Collapse sheet list" : "Expand sheet list"}>
              {railOpen ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
            </button>
          </div>
        </nav>

        {/* -------------------------------------- canvas */}
        <main className="canvas">
          <div className="toolbar">
            <FileText size={15} color="var(--ink-3)" />
            <strong style={{ fontSize: 13 }}>{sheet.number}</strong>
            <span style={{ fontSize: 13, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sheet.title}</span>
            <div className="toolbar__rule" />
            <div className="toolgroup">
              <button className="iconbtn" aria-pressed={tool === "pan"} onClick={() => setTool("pan")} title="Pan"><Hand size={15} /></button>
              <button className="iconbtn" aria-pressed={tool === "calibrate"} onClick={() => setTool(tool === "calibrate" ? "pan" : "calibrate")} title="Calibrate scale"><Ruler size={15} /></button>
            </div>
            <div className="toolbar__rule" />
            <button className="iconbtn" onClick={() => canvasCmd("out")} title="Zoom out"><ZoomOut size={15} /></button>
            <span className="zoomval">Zoom</span>
            <button className="iconbtn" onClick={() => canvasCmd("in")} title="Zoom in"><ZoomIn size={15} /></button>
            <button className="iconbtn" onClick={() => canvasCmd("fit")} title="Fit page"><Maximize2 size={15} /> Fit</button>
            <div className="toolbar__rule" />
            <button className="iconbtn" aria-pressed={showFind} onClick={() => setShowFind((v) => !v)} title="Find on sheet"><Search size={15} /></button>
            {showFind && (
              <input className="field" style={{ width: 170, minHeight: 28 }} value={canvasQuery} onChange={(e) => setCanvasQuery(e.target.value)} placeholder="Find on this sheet" aria-label="Find on this sheet" />
            )}
            <div style={{ position: "relative" }}>
              <button className="iconbtn" aria-pressed={menu === "layers"} onClick={() => setMenu(menu === "layers" ? null : "layers")}><Layers size={15} /> Layers</button>
              {menu === "layers" && (
                <div className="popover" style={{ top: 38, left: 0 }}>
                  {[["detected", "Detected items"], ["approved", "Approved items"], ["rejected", "Rejected items"], ["measurements", "Measurements"], ["warnings", "Warnings"], ["legend", "Legend"]].map(([k, l]) => (
                    <label className="switch" key={k}>
                      <input type="checkbox" checked={layers[k]} onChange={(e) => setLayers((p) => ({ ...p, [k]: e.target.checked }))} />
                      {l}
                    </label>
                  ))}
                </div>
              )}
            </div>
            <div className="spacer" />
            <span style={{ fontSize: 12, color: "var(--ink-3)" }}>
              {sheet.scale === "none" ? "No scale set" : sheet.scale === "mixed" ? "Mixed scale" : sheet.scale === "nts" ? "Not to scale" : sheet.scale}
            </span>
          </div>

          <BlueprintCanvas
            sheet={sheet}
            items={items}
            selectedId={selId}
            onSelect={select}
            layers={layers}
            tool={tool}
            searchTerm={canvasQuery}
            remoteSelections={remoteSelections}
            onCalibrate={() => setModal({ kind: "scale" })}
          />
        </main>

        {/* -------------------------------------- detail */}
        <aside className="detail" aria-label="Selected item">
          {sel ? (
            <>
              <div className="detail__scroll">
                <div className="detail__head">
                  <Pill status={sel.status} />
                  <span style={{ fontSize: 12, color: "var(--ink-3)" }}>{SYMBOL_LABELS[sel.symbol]}</span>
                </div>

                {!edit ? (
                  <>
                    <h2>{sel.name}</h2>
                    <p className="value value--muted" style={{ margin: "6px 0 0" }}>{sel.description}</p>

                    <p className="label">Quantity</p>
                    <p className="qty tabular">
                      {sel.quantity.toLocaleString()}
                      <small>{sel.unit}</small>
                    </p>

                    <p className="label">Classification</p>
                    <p className="value">{sel.system} — {sel.category}</p>

                    <p className="label">Location</p>
                    <p className="value">Sheet {sel.sheetId} · {sheets.find((s) => s.id === sel.sheetId)?.revision}</p>

                    <p className="label">Source evidence</p>
                    <button className="linkbtn" onClick={() => setModal({ kind: "evidence", item: sel })}>
                      {sel.evidence.detail}, {sel.evidence.sheet} <ExternalLink size={12} style={{ verticalAlign: -1 }} />
                    </button>

                    {sel.warning && (
                      <div className={"warncard warncard--" + (sel.status === "missing" ? "missing" : "attention")}>
                        <h4>{sel.warning.title}</h4>
                        <p>{sel.warning.found}</p>
                        <dl style={{ margin: 0 }}>
                          <dt>Why it matters</dt>
                          <dd>{sel.warning.why}</dd>
                          <dt>What to do</dt>
                          <dd>{sel.warning.fix}</dd>
                          <dt>Where to look</dt>
                          <dd>{sel.warning.where}</dd>
                        </dl>
                      </div>
                    )}

                    {sel.approvedBy && (
                      <>
                        <p className="label">Approved by</p>
                        <p className="value">{sel.approvedBy}</p>
                      </>
                    )}

                    {sel.notes && (
                      <>
                        <p className="label">Notes</p>
                        <p className="value">{sel.notes}</p>
                      </>
                    )}

                    <div className="actions">
                      <button className="btn btn--primary" onClick={() => setStatus(sel.id, "approved")} disabled={sel.status === "missing"}>
                        <Check size={14} /> Approve item
                      </button>
                    </div>
                    {sel.status === "missing" && (
                      <p style={{ fontSize: 12, color: "var(--ink-2)", marginTop: 7 }}>
                        Resolve the scale on this sheet before approving a measured item.
                      </p>
                    )}
                    <div className="actions">
                      <button className="btn" onClick={() => setEdit({ system: sel.system, category: sel.category, quantity: sel.quantity, notes: sel.notes || "", symbol: sel.symbol })}><Pencil size={13} /> Edit</button>
                      <button className="btn" onClick={() => setStatus(sel.id, "rejected")}><CircleSlash size={13} /> Reject</button>
                      <button className="btn" onClick={() => setModal({ kind: "delete", id: sel.id })}><Trash2 size={13} /></button>
                    </div>
                  </>
                ) : (
                  <>
                    <h2>Edit item</h2>
                    <p className="label">Symbol</p>
                    <select className="field" value={edit.symbol} onChange={(e) => setEdit({ ...edit, symbol: e.target.value })}>
                      {Object.entries(SYMBOL_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                    </select>
                    <p className="label">System</p>
                    <select className="field" value={edit.system} onChange={(e) => setEdit({ ...edit, system: e.target.value })}>
                      {SYSTEMS.map((s) => <option key={s}>{s}</option>)}
                    </select>
                    <p className="label">Category</p>
                    <input className="field" value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} />
                    <p className="label">Quantity ({sel.unit})</p>
                    <input className="field tabular" type="number" min="0" value={edit.quantity} onChange={(e) => setEdit({ ...edit, quantity: e.target.value })} />
                    <p className="label">Notes</p>
                    <textarea className="field" rows={3} value={edit.notes} onChange={(e) => setEdit({ ...edit, notes: e.target.value })} placeholder="Anything the next reviewer should know" />
                    <div className="actions">
                      <button className="btn btn--primary" onClick={saveEdit}>Save changes</button>
                      <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
                    </div>
                  </>
                )}
              </div>
              <div className="detail__nav">
                <button className="iconbtn" onClick={() => step(-1)}><ChevronLeft size={14} /> Previous</button>
                <span style={{ fontSize: 12, color: "var(--ink-3)" }}>
                  {items.filter((i) => i.sheetId === sheetId).findIndex((i) => i.id === selId) + 1} of {items.filter((i) => i.sheetId === sheetId).length}
                </span>
                <button className="iconbtn" onClick={() => step(1)}>Next <ChevronRight size={14} /></button>
              </div>
            </>
          ) : (
            <div className="detail__scroll">
              <h2>Review progress</h2>
              <div className="progressbar" style={{ margin: "12px 0 8px" }}>
                {STATUS_ORDER.filter((k) => counts[k]).map((k) => (
                  <i key={k} style={{ width: (counts[k] / items.length) * 100 + "%", background: STATUS[k].color }} />
                ))}
              </div>
              <p className="value value--muted">{counts.approved} of {items.length} items approved</p>

              {STATUS_ORDER.filter((k) => counts[k]).map((k) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: "1px solid var(--line-1)" }}>
                  <Pill status={k} />
                  <span className="tabular" style={{ fontSize: 13, fontWeight: 600 }}>{counts[k]}</span>
                </div>
              ))}

              {(counts.missing || counts.attention) ? (
                <>
                  <p className="label">Next recommended issue</p>
                  <p className="value value--muted" style={{ marginBottom: 10 }}>
                    {counts.missing ? "Missing information blocks approval, so start there." : "Conflicting information needs a decision before export."}
                  </p>
                  <button className="btn btn--primary btn--block" onClick={nextIssue}>Open next issue</button>
                </>
              ) : (
                <p className="value" style={{ marginTop: 16, color: "var(--green)", fontWeight: 600 }}>Every item has been reviewed.</p>
              )}

              <p className="label">On this sheet</p>
              <p className="value value--muted">Select a symbol on the drawing to review its details, or press J to step through items.</p>
            </div>
          )}
        </aside>
      </div>

      {/* ---------------------------------------- drawer */}
      <div className="drawer">
        <button className="drawer__strip" onClick={() => setDrawerOpen((v) => !v)} aria-expanded={drawerOpen}>
          <span className="stat"><b className="tabular">{counts.approved}</b><span>Approved</span></span>
          <span className="stat"><b className="tabular">{counts.ready + counts.attention + counts.missing}</b><span>Remaining</span></span>
          <span className="stat"><b className="tabular" style={{ color: counts.attention ? "var(--amber)" : undefined }}>{counts.attention}</b><span>Needs attention</span></span>
          <span className="stat"><b className="tabular" style={{ color: counts.missing ? "var(--red)" : undefined }}>{counts.missing}</b><span>Missing information</span></span>
          <span className="stat"><b className="tabular">{approvedQty.toLocaleString()}</b><span>Approved units</span></span>
          <span className="spacer" />
          <span style={{ fontSize: 12, color: "var(--ink-3)", display: "flex", alignItems: "center", gap: 5 }}>
            {drawerOpen ? "Hide totals" : "System totals"} {drawerOpen ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
          </span>
        </button>
        {drawerOpen && (
          <div className="drawer__panel">
            {bySystem.map((r) => (
              <div key={r.system}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span>{r.system}</span>
                  <span className="tabular" style={{ fontWeight: 600 }}>{r.approved}/{r.total}</span>
                </div>
                <div className="progressbar"><i style={{ width: (r.approved / r.total) * 100 + "%", background: "var(--green)" }} /></div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---------------------------------------- toast */}
      {toast && (
        <div className="toast" role="status">
          {toast.text}
          <button onClick={() => { undo(); setToast(null); }}>Undo</button>
        </div>
      )}

      {/* ---------------------------------------- modals */}
      {modal?.kind === "scale" && (
        <Modal title={sheet.scale === "none" ? "Set drawing scale" : "Confirm drawing scale"} onClose={() => setModal(null)}>
          <p style={{ margin: "0 0 12px", fontSize: 13.5, color: "var(--ink-2)" }}>
            {sheet.number} — choosing a scale recalculates every measured item on this sheet and clears the related warnings.
          </p>
          {sheet.scaleOptions.map((s) => (
            <button key={s} className="btn btn--block" style={{ justifyContent: "flex-start", marginBottom: 8 }} onClick={() => applyScale(s)}>{s}</button>
          ))}
          <button className="btn btn--block" style={{ justifyContent: "flex-start" }} onClick={() => { setModal(null); setTool("calibrate"); }}>
            <Ruler size={14} /> Calibrate against a known dimension instead
          </button>
        </Modal>
      )}

      {modal?.kind === "evidence" && (
        <Modal title="Source evidence" onClose={() => setModal(null)}>
          <div style={{ border: "1px solid var(--line-2)", borderRadius: 6, background: "var(--sheet)", padding: 14, marginBottom: 12 }}>
            <svg viewBox="0 0 320 150" width="100%" height="150">
              <rect x="8" y="8" width="304" height="134" fill="#fdfcf9" stroke="#b8b3a9" />
              <line x1="8" y1="42" x2="312" y2="42" stroke="#cfcbc0" />
              <text x="18" y="30" fontSize="11" fill="#5f5b54" fontWeight="700">{modal.item.evidence.sheet} — {modal.item.evidence.detail}</text>
              <g transform="translate(160 95)">
                <SymbolGlyph kind={modal.item.symbol} color={STATUS[modal.item.status].color} />
              </g>
              <rect x="120" y="60" width="80" height="70" fill="none" stroke={STATUS[modal.item.status].color} strokeWidth="1.6" strokeDasharray="5 4" />
            </svg>
          </div>
          <p style={{ margin: 0, fontSize: 13.5 }}>
            This is the region of {modal.item.evidence.sheet} the quantity was read from. Opening evidence never leaves your place in the review.
          </p>
        </Modal>
      )}

      {modal?.kind === "delete" && (
        <Modal title="Delete item" onClose={() => setModal(null)}
          foot={
            <>
              <button className="btn" onClick={() => setModal(null)}>Cancel</button>
              <button className="btn btn--danger" onClick={() => removeItem(modal.id)}>Delete item</button>
            </>
          }>
          <p style={{ margin: 0, fontSize: 13.5 }}>This removes the item from the takeoff and from every total. You can undo it afterward, and other reviewers will see the change.</p>
        </Modal>
      )}

      {modal?.kind === "help" && (
        <Modal title="Keyboard shortcuts" onClose={() => setModal(null)}>
          {[["A", "Approve the selected item"], ["E", "Edit the selected item"], ["R", "Reject the selected item"], ["J / K", "Next / previous item"], ["+ / −", "Zoom in / out"], ["0", "Fit page"], ["Ctrl or ⌘ Z", "Undo"], ["⇧ Ctrl or ⌘ Z", "Redo"], ["Esc", "Close this dialog"]].map(([k, l]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", fontSize: 13.5 }}>
              <span className="kbd">{k}</span>
              <span style={{ color: "var(--ink-2)" }}>{l}</span>
            </div>
          ))}
          <p style={{ fontSize: 12.5, color: "var(--ink-3)", marginBottom: 0 }}>Single-key shortcuts stay off while you are typing in a field.</p>
        </Modal>
      )}

      {modal?.kind === "finish" && (
        <Modal title="Review summary" onClose={() => setModal(null)}
          foot={
            <>
              <button className="btn" onClick={() => setModal(null)}>Return to review</button>
              <button className="btn btn--primary" disabled={blocking.length > 0 || (soft.length > 0 && !ack)} onClick={() => setModal({ kind: "done" })}>
                Complete review
              </button>
            </>
          }>
          {blocking.length > 0 && (
            <>
              <p className="label" style={{ color: "var(--red)", marginTop: 0 }}>Must be resolved before finishing</p>
              {blocking.map((i) => (
                <div className="issuerow" key={i.id}>
                  <span><strong>{i.name}</strong> · {i.sheetId} — {i.warning?.title}</span>
                  <button className="linkbtn" onClick={() => { setModal(null); select(i.id); }}>Go to item</button>
                </div>
              ))}
            </>
          )}
          {soft.length > 0 && (
            <>
              <p className="label" style={{ color: "var(--amber)" }}>Can remain as acknowledged allowances</p>
              {soft.map((i) => (
                <div className="issuerow" key={i.id}>
                  <span><strong>{i.name}</strong> · {i.sheetId} — {i.warning?.title}</span>
                  <button className="linkbtn" onClick={() => { setModal(null); select(i.id); }}>Go to item</button>
                </div>
              ))}
              {blocking.length === 0 && (
                <label className="switch" style={{ marginTop: 10, alignItems: "flex-start" }}>
                  <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} style={{ marginTop: 2 }} />
                  <span>I acknowledge these items are unresolved and accept them as allowances in the exported takeoff.</span>
                </label>
              )}
            </>
          )}
          {!blocking.length && !soft.length && (
            <p style={{ margin: 0, fontSize: 14, color: "var(--green)", fontWeight: 600 }}>Every item has been reviewed. This takeoff is ready to export.</p>
          )}
        </Modal>
      )}

      {modal?.kind === "done" && (
        <Modal title="Review complete" onClose={() => setModal(null)}
          foot={<button className="btn btn--primary" onClick={() => setModal(null)}>Back to workspace</button>}>
          <p style={{ marginTop: 0, fontSize: 13.5 }}>
            {counts.approved} approved items totalling {approvedQty.toLocaleString()} units are ready for export preview. In the full product this hands off to screen H.
          </p>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, children, onClose, foot }) {
  return (
    <div className="scrim" onClick={onClose} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h3>{title}</h3>
          <button className="iconbtn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="modal__body">{children}</div>
        {foot && <div className="modal__foot">{foot}</div>}
      </div>
    </div>
  );
}
