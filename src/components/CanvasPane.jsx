import { FileText, Hand, Ruler, ZoomOut, ZoomIn, Maximize2, Search, Layers } from "lucide-react";
import BlueprintCanvas from "./BlueprintCanvas.jsx";
import { displayStatus } from "./Pill.jsx";

const LAYER_LABELS = [
  ["detected", "Detected items"],
  ["approved", "Approved items"],
  ["rejected", "Rejected items"],
  ["measurements", "Measurements"],
  ["warnings", "Warnings"],
  ["legend", "Legend"],
];

export const canvasCmd = (type) => window.dispatchEvent(new CustomEvent("canvas-cmd", { detail: { type } }));

/** The toolbar plus BlueprintCanvas.jsx itself (unedited except line
 *  256's warning-badge check — see that file). BlueprintCanvas reads
 *  `item.status` directly for layer visibility and marker color and has
 *  no idea `rejected` is a separate boolean now, so this is the one
 *  place that adapts the item shape for it (task-16-brief.md, "If a
 *  prop shape no longer matches, adapt it in App.jsx"). */
export default function CanvasPane({
  sheet, items, selId, onSelect, layers, onLayersChange, tool, onToolChange,
  canvasQuery, onCanvasQuery, showFind, onToggleFind, menu, onToggleMenu,
  remoteSelections, onCalibrate,
}) {
  const canvasItems = items.map((i) => ({ ...i, status: displayStatus(i) }));

  return (
    <main className="canvas">
      <div className="toolbar">
        <FileText size={15} color="var(--ink-3)" />
        <strong style={{ fontSize: 13 }}>{sheet.number}</strong>
        <span style={{ fontSize: 13, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{sheet.title}</span>
        <div className="toolbar__rule" />
        <div className="toolgroup">
          <button className="iconbtn" aria-pressed={tool === "pan"} onClick={() => onToolChange("pan")} title="Pan"><Hand size={15} /></button>
          <button className="iconbtn" aria-pressed={tool === "calibrate"} onClick={() => onToolChange(tool === "calibrate" ? "pan" : "calibrate")} title="Calibrate scale"><Ruler size={15} /></button>
        </div>
        <div className="toolbar__rule" />
        <button className="iconbtn" onClick={() => canvasCmd("out")} title="Zoom out"><ZoomOut size={15} /></button>
        <span className="zoomval">Zoom</span>
        <button className="iconbtn" onClick={() => canvasCmd("in")} title="Zoom in"><ZoomIn size={15} /></button>
        <button className="iconbtn" onClick={() => canvasCmd("fit")} title="Fit page"><Maximize2 size={15} /> Fit</button>
        <div className="toolbar__rule" />
        <button className="iconbtn" aria-pressed={showFind} onClick={onToggleFind} title="Find on sheet"><Search size={15} /></button>
        {showFind && (
          <input className="field" style={{ width: 170, minHeight: 28 }} value={canvasQuery} onChange={(e) => onCanvasQuery(e.target.value)} placeholder="Find on this sheet" aria-label="Find on this sheet" />
        )}
        <div style={{ position: "relative" }}>
          <button className="iconbtn" aria-pressed={menu === "layers"} onClick={() => onToggleMenu(menu === "layers" ? null : "layers")}><Layers size={15} /> Layers</button>
          {menu === "layers" && (
            <div className="popover" style={{ top: 38, left: 0 }}>
              {LAYER_LABELS.map(([k, l]) => (
                <label className="switch" key={k}>
                  <input type="checkbox" checked={layers[k]} onChange={(e) => onLayersChange({ ...layers, [k]: e.target.checked })} />
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
        items={canvasItems}
        selectedId={selId}
        onSelect={onSelect}
        layers={layers}
        tool={tool}
        searchTerm={canvasQuery}
        remoteSelections={remoteSelections}
        onCalibrate={onCalibrate}
      />
    </main>
  );
}
