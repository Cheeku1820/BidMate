import { useEffect, useState } from "react";
import { SYSTEMS } from "../lib/vocabulary.js";
import { useNavigate } from "react-router-dom";
import { useWorkspaceContext } from "./project/useWorkspaceContext.js";
import TopBar from "./TopBar.jsx";
import SheetsRail from "./SheetsRail.jsx";
import CanvasPane, { canvasCmd } from "./CanvasPane.jsx";
import ItemDetailPanel from "./ItemDetailPanel.jsx";
import SummaryDrawer from "./SummaryDrawer.jsx";
import FinishReviewModal from "./FinishReviewModal.jsx";
import { ScaleModal, EvidenceModal, DeleteModal, HelpModal } from "./MiscModals.jsx";

/** The review workspace itself (spec §5, screen F) — everything between
 *  signing in and Finish review. Owns local UI state only (filters,
 *  modals, the in-progress edit draft); the store subscription and the
 *  cross-view selection now live in ProjectWorkspaceLayout, shared with
 *  every other view of the same project (the takeoff spreadsheet is the
 *  next one), reached here through useWorkspaceContext(). */
export default function Workspace() {
  const {
    snapshot, loading, loadError, saved, toast, dismissToast,
    itemError, clearItemError, setPresenceTarget, refresh,
    approveItem, rejectItem, deleteItem, editItem, setScale, undo, redo,
    me, sheetId, setSheetId, selectedItemId, selectItem, project, projectId,
  } = useWorkspaceContext();
  const navigate = useNavigate();

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

  const sheets = snapshot?.sheets ?? [];
  const items = snapshot?.items ?? [];
  const sheet = sheets.find((s) => s.id === sheetId) ?? sheets[0] ?? null;
  const sel = items.find((i) => i.id === selectedItemId) ?? null;

  useEffect(() => {
    setPresenceTarget(sheetId, selectedItemId);
  }, [sheetId, selectedItemId, setPresenceTarget]);

  const others = snapshot?.presence ?? [];
  const remoteSelections = others.filter((p) => p.sheetId === sheetId && p.itemId).map((p) => ({ itemId: p.itemId, color: p.color, name: p.name }));

  function select(id) {
    selectItem(id);
    setEdit(null);
    clearItemError();
  }

  function step(dir) {
    const list = items.filter((i) => i.sheetId === sheetId);
    if (!list.length) return;
    const i = list.findIndex((x) => x.id === selectedItemId);
    select(list[i === -1 ? 0 : (i + dir + list.length) % list.length].id);
  }

  function nextIssue() {
    const it = items.find((i) => i.status === "missing" && !i.rejected) || items.find((i) => i.status === "attention" && !i.rejected);
    if (it) select(it.id);
  }

  async function refreshItem() {
    await refresh();
    clearItemError();
  }

  function startEdit(item) {
    setEdit({ system: item.system, category: item.category, quantity: item.quantity, notes: item.notes || "", symbol: item.symbol });
  }

  async function saveEdit(item) {
    if (!edit) return;
    const changes = { system: edit.system, category: edit.category, quantity: Number(edit.quantity) || 0, notes: edit.notes, symbol: edit.symbol };
    const res = await editItem(item.id, changes, item.version);
    if (res) setEdit(null);
  }

  async function confirmDelete(item) {
    const res = await deleteItem(item.id, item.version);
    if (res) {
      if (selectedItemId === item.id) selectItem(null);
      setModal(null);
    }
  }

  async function doUndo() {
    try {
      await undo();
    } catch {
      /* saved-state already reflects the failure; nothing else to do */
    }
  }
  async function doRedo() {
    try {
      await redo();
    } catch {
      /* same as doUndo */
    }
  }

  async function applyScale(value) {
    try {
      await setScale(sheet.id, value);
      setModal(null);
      setTool("pan");
    } catch {
      /* saved-state already reflects the failure */
    }
  }

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
        if (e.shiftKey) doRedo();
        else doUndo();
        return;
      }
      if (typing || e.metaKey || e.ctrlKey) return;
      if (e.key === "Escape") { setModal(null); setMenu(null); setEdit(null); return; }
      if (e.key === "a" && sel) approveItem(sel.id, sel.version);
      else if (e.key === "e" && sel) startEdit(sel);
      else if (e.key === "r" && sel) rejectItem(sel.id, sel.version);
      else if (e.key === "j") step(1);
      else if (e.key === "k") step(-1);
      else if (e.key === "+" || e.key === "=") canvasCmd("in");
      else if (e.key === "-") canvasCmd("out");
      else if (e.key === "0") canvasCmd("fit");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (loading) {
    return (
      <div className="app">
        <p style={{ margin: "auto", fontSize: 14, color: "var(--ink-2)" }}>Loading this project…</p>
      </div>
    );
  }

  if (loadError || !sheet) {
    return (
      <div className="app">
        <div style={{ margin: "auto", textAlign: "center", maxWidth: 360 }}>
          <p style={{ fontSize: 14, color: "var(--ink-2)", marginBottom: 12 }}>{loadError || "This project has no sheets yet."}</p>
          <button className="btn btn--primary" onClick={refresh}>Try again</button>
        </div>
      </div>
    );
  }

  const totals = snapshot.totals;
  const counts = {
    missing: totals.missingCount,
    attention: totals.attentionCount,
    ready: Math.max(totals.remainingCount - totals.attentionCount - totals.missingCount, 0),
    approved: totals.approvedCount,
    rejected: items.filter((i) => i.rejected).length,
  };
  const blocking = items.filter((i) => i.status === "missing" && !i.rejected);
  const soft = items.filter((i) => i.status === "attention" && !i.rejected);
  const bySystem = SYSTEMS.map((s) => {
    const list = items.filter((i) => i.system === s);
    return { system: s, approved: list.filter((i) => i.status === "approved" && !i.rejected).length, total: list.length };
  }).filter((r) => r.total);
  const overall = counts.missing ? "missing" : counts.attention ? "attention" : counts.ready ? "ready" : "approved";
  const itemsOnSheet = items.filter((i) => i.sheetId === sheetId);
  const stepIndex = itemsOnSheet.findIndex((i) => i.id === selectedItemId) + 1;

  return (
    <div className="app">
      <p className="too-narrow">Use a larger screen to review drawings. This workspace needs at least 1024px of width.</p>

      <TopBar
        overall={overall}
        {...(project?.name ? { title: project.name } : {})}
        {...(project?.revisionSetLabel ? { subtitle: `Active set: ${project.revisionSetLabel}` } : {})}
        saved={saved}
        me={me}
        presence={others}
        undoState={snapshot.undo}
        onUndo={doUndo}
        onRedo={doRedo}
        onHelp={() => setModal({ kind: "help" })}
        onFinish={() => setModal({ kind: "finish" })}
      />

      <div className="workspace">
        <SheetsRail
          sheets={sheets}
          items={items}
          sheetId={sheetId}
          onSelectSheet={setSheetId}
          filter={filter}
          onFilter={setFilter}
          query={sheetQuery}
          onQuery={setSheetQuery}
          open={railOpen}
          onToggleOpen={() => setRailOpen((v) => !v)}
        />

        <CanvasPane
          sheet={sheet}
          items={items}
          sheetImageUrl={
            sheet?.takeoffId && sheet?.pageIndex
              ? `http://localhost:8100/sheet-image?takeoff_id=${sheet.takeoffId}&page=${sheet.pageIndex}`
              : null
          }
          selId={selectedItemId}
          onSelect={select}
          layers={layers}
          onLayersChange={setLayers}
          tool={tool}
          onToolChange={setTool}
          canvasQuery={canvasQuery}
          onCanvasQuery={setCanvasQuery}
          showFind={showFind}
          onToggleFind={() => setShowFind((v) => !v)}
          menu={menu}
          onToggleMenu={setMenu}
          remoteSelections={remoteSelections}
          onCalibrate={() => setModal({ kind: "scale" })}
        />

        <ItemDetailPanel
          sel={sel}
          sheets={sheets}
          currentSheet={sheet}
          edit={edit}
          onStartEdit={startEdit}
          onChangeEdit={setEdit}
          onSaveEdit={saveEdit}
          onCancelEdit={() => setEdit(null)}
          onApprove={(item) => approveItem(item.id, item.version)}
          onReject={(item) => rejectItem(item.id, item.version)}
          onRequestDelete={(item) => setModal({ kind: "delete", item })}
          onShowEvidence={(item) => setModal({ kind: "evidence", item })}
          onStep={step}
          stepIndex={stepIndex}
          stepCount={itemsOnSheet.length}
          itemError={itemError}
          onRefreshItem={refreshItem}
          onDismissItemError={clearItemError}
          counts={counts}
          itemsTotal={items.length}
          onNextIssue={nextIssue}
        />
      </div>

      <SummaryDrawer totals={totals} bySystem={bySystem} open={drawerOpen} onToggle={() => setDrawerOpen((v) => !v)} />

      {toast && (
        <div className="toast" role="status">
          {toast.text}
          <button onClick={() => { doUndo(); dismissToast(); }}>Undo</button>
        </div>
      )}

      {modal?.kind === "scale" && (
        <ScaleModal sheet={sheet} onApplyScale={applyScale} onCalibrate={() => { setModal(null); setTool("calibrate"); }} onClose={() => setModal(null)} />
      )}
      {modal?.kind === "evidence" && <EvidenceModal item={modal.item} onClose={() => setModal(null)} />}
      {modal?.kind === "delete" && <DeleteModal item={modal.item} onConfirm={confirmDelete} onClose={() => setModal(null)} />}
      {modal?.kind === "help" && <HelpModal onClose={() => setModal(null)} />}
      {modal?.kind === "finish" && (
        <FinishReviewModal
          blocking={blocking}
          soft={soft}
          ack={ack}
          onAckChange={setAck}
          onGoToItem={(item) => { setModal(null); select(item.id); }}
          onClose={() => setModal(null)}
          onComplete={() => {
            // Finishing review leads to the export preview (spec §11
            // path 5: resolve/acknowledge -> preview approved totals ->
            // export), not a terminal confirmation dialog.
            setModal(null);
            navigate(`/projects/${projectId}/export`);
          }}
        />
      )}
    </div>
  );
}
