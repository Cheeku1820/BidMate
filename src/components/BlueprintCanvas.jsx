import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import PlanDrawing from "./PlanDrawing.jsx";
import { SymbolGlyph } from "./Symbols.jsx";
import { STATUS } from "../lib/vocabulary.js";

export const SHEET_W = 1000;
export const SHEET_H = 750;

const MIN_SCALE = 0.25;
const MAX_SCALE = 6;

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

function pathLength(points) {
  let total = 0;
  for (let i = 1; i < points.length; i += 1) {
    total += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
  }
  return total;
}

/* --------------------------------------------------------------- */

export default function BlueprintCanvas({
  sheet,
  items,
  sheetImageUrl,
  selectedId,
  onSelect,
  layers,
  tool,
  onCalibrate,
  remoteSelections,
  searchTerm,
}) {
  const viewportRef = useRef(null);
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const [size, setSize] = useState({ w: 900, h: 600 });
  const [panning, setPanning] = useState(false);
  const [hover, setHover] = useState(null);
  const [calibPoints, setCalibPoints] = useState([]);
  const dragRef = useRef(null);

  /* --- fit ------------------------------------------------------ */

  const fit = useCallback(
    (w = size.w, h = size.h) => {
      const pad = 48;
      const scale = Math.min((w - pad * 2) / SHEET_W, (h - pad * 2) / SHEET_H);
      setView({ scale, tx: (w - SHEET_W * scale) / 2, ty: (h - SHEET_H * scale) / 2 });
    },
    [size.w, size.h]
  );

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ w: width, h: height });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const bootRef = useRef(false);
  useEffect(() => {
    if (size.w > 0 && !bootRef.current) {
      bootRef.current = true;
      fit(size.w, size.h);
    }
  }, [size, fit]);

  useEffect(() => {
    setCalibPoints([]);
  }, [tool, sheet.id]);

  /* --- imperative zoom API through window events ----------------- */

  const zoomAt = useCallback((factor, cx, cy) => {
    setView((v) => {
      const next = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE);
      const k = next / v.scale;
      return { scale: next, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k };
    });
  }, []);

  useEffect(() => {
    function onCmd(e) {
      const { type } = e.detail || {};
      if (type === "in") zoomAt(1.25, size.w / 2, size.h / 2);
      if (type === "out") zoomAt(0.8, size.w / 2, size.h / 2);
      if (type === "fit") fit();
    }
    window.addEventListener("canvas-cmd", onCmd);
    return () => window.removeEventListener("canvas-cmd", onCmd);
  }, [zoomAt, fit, size]);

  /* --- pointer --------------------------------------------------- */

  function toSheet(clientX, clientY) {
    const rect = viewportRef.current.getBoundingClientRect();
    return {
      x: (clientX - rect.left - view.tx) / view.scale,
      y: (clientY - rect.top - view.ty) / view.scale,
    };
  }

  function onWheel(e) {
    e.preventDefault();
    const rect = viewportRef.current.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    zoomAt(e.deltaY < 0 ? 1.12 : 0.89, cx, cy);
  }

  function onPointerDown(e) {
    if (tool === "calibrate") return;
    dragRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty };
    setPanning(true);
    e.currentTarget.setPointerCapture(e.pointerId);
  }

  function onPointerMove(e) {
    if (!dragRef.current) return;
    const d = dragRef.current;
    setView((v) => ({ ...v, tx: d.tx + (e.clientX - d.x), ty: d.ty + (e.clientY - d.y) }));
  }

  function onPointerUp(e) {
    dragRef.current = null;
    setPanning(false);
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  }

  function onClick(e) {
    if (tool !== "calibrate") return;
    const p = toSheet(e.clientX, e.clientY);
    const next = [...calibPoints, [p.x, p.y]];
    if (next.length === 2) {
      onCalibrate(pathLength(next));
      setCalibPoints([]);
    } else {
      setCalibPoints(next);
    }
  }

  /* --- derived --------------------------------------------------- */

  const visible = useMemo(
    () =>
      items.filter((it) => {
        if (it.sheetId !== sheet.id) return false;
        if (it.status === "approved") return layers.approved;
        if (it.status === "rejected") return layers.rejected;
        return layers.detected;
      }),
    [items, sheet.id, layers]
  );

  const dimmed = (it) =>
    searchTerm && !(it.name + " " + it.description + " " + it.system).toLowerCase().includes(searchTerm.toLowerCase());

  const scaleUnknown = sheet.scale === "none" || sheet.scale === "mixed";

  return (
    <div
      ref={viewportRef}
      className={"viewport" + (panning ? " viewport--panning" : "") + (tool === "calibrate" ? " viewport--measuring" : "")}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
      onClick={onClick}
      role="application"
      aria-label={`Blueprint canvas for sheet ${sheet.number}`}
    >
      <div
        className="stage"
        style={{ transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.scale})` }}
      >
        <div className="sheetpaper" style={{ width: SHEET_W, height: SHEET_H }}>
          <svg width={SHEET_W} height={SHEET_H} viewBox={`0 0 ${SHEET_W} ${SHEET_H}`}>
            {/* Real projects render the actual rendered PDF page behind the
                markers (item coordinates were normalized to this space at
                ingest, so preserveAspectRatio="none" keeps them aligned).
                The seed fixture falls back to the drawn geometry. */}
            {sheetImageUrl ? (
              <image href={sheetImageUrl} x={0} y={0} width={SHEET_W} height={SHEET_H} preserveAspectRatio="none" />
            ) : (
              <PlanDrawing sheet={sheet} />
            )}

            {/* measured runs */}
            {layers.measurements &&
              visible
                .filter((it) => it.path)
                .map((it) => {
                  const meta = STATUS[it.status];
                  const sel = it.id === selectedId;
                  const mid = it.path[Math.floor(it.path.length / 2)];
                  return (
                    <g key={it.id + "-path"} opacity={dimmed(it) ? 0.18 : 1}>
                      <polyline
                        points={it.path.map((p) => p.join(",")).join(" ")}
                        fill="none"
                        stroke={meta.color}
                        strokeWidth={sel ? 4.5 : 3}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        strokeDasharray={it.status === "missing" ? "9 6" : undefined}
                        opacity={sel ? 1 : 0.85}
                      />
                      {it.path.map((p, i) => (
                        <circle key={i} cx={p[0]} cy={p[1]} r="3.4" fill="#fff" stroke={meta.color} strokeWidth="2" />
                      ))}
                      <g transform={`translate(${mid[0] + 10} ${mid[1] - 10})`}>
                        <rect x="0" y="-13" width="74" height="19" rx="3" fill="#fff" stroke={meta.color} strokeWidth="1.1" />
                        <text x="6" y="0" fill={meta.color} fontSize="12" fontWeight="700">
                          {it.quantity} {it.unit}
                        </text>
                      </g>
                    </g>
                  );
                })}

            {/* point markers */}
            {visible
              .filter((it) => !it.path)
              .map((it) => {
                const meta = STATUS[it.status];
                const sel = it.id === selectedId;
                const remote = remoteSelections.find((r) => r.itemId === it.id);
                return (
                  <g
                    key={it.id}
                    transform={`translate(${it.x} ${it.y})`}
                    opacity={dimmed(it) ? 0.18 : 1}
                    style={{ cursor: "pointer" }}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelect(it.id);
                    }}
                    onMouseEnter={() => setHover(it.id)}
                    onMouseLeave={() => setHover(null)}
                    tabIndex={0}
                    role="button"
                    aria-label={`${it.name}, ${meta.label}, ${it.quantity} ${it.unit}`}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelect(it.id);
                      }
                    }}
                  >
                    <circle r="19" fill={sel ? meta.color : "transparent"} opacity={sel ? 0.14 : 0} />
                    {sel && <circle r="17" fill="none" stroke={meta.color} strokeWidth="2" />}
                    {remote && !sel && <circle r="17" fill="none" stroke={remote.color} strokeWidth="2" strokeDasharray="4 3" />}
                    <circle r="13" fill="#fff" opacity="0.85" />
                    <SymbolGlyph kind={it.symbol} color={meta.color} />
                    {it.warnings?.length > 0 && layers.warnings && (
                      <g transform="translate(9 -9)">
                        <circle r="6" fill={STATUS[it.status].color} stroke="#fff" strokeWidth="1.6" />
                        <text y="0.5" fill="#fff" fontSize="9" fontWeight="700" textAnchor="middle" dominantBaseline="central">
                          !
                        </text>
                      </g>
                    )}
                  </g>
                );
              })}

            {/* calibration in progress */}
            {calibPoints.length === 1 && (
              <circle cx={calibPoints[0][0]} cy={calibPoints[0][1]} r="5" fill="none" stroke="#23528f" strokeWidth="2" />
            )}
          </svg>
        </div>
      </div>

      {/* hover tooltip */}
      {hover &&
        (() => {
          const it = items.find((i) => i.id === hover);
          if (!it || it.path) return null;
          const meta = STATUS[it.status];
          return (
            <div className="tooltip" style={{ left: view.tx + it.x * view.scale, top: view.ty + it.y * view.scale - 22 }}>
              {it.name}
              <span>
                {it.quantity} {it.unit} · {meta.label}
              </span>
            </div>
          );
        })()}

      {/* scale banner */}
      {scaleUnknown && (
        <div className="overlay" style={{ top: 14, left: 14, right: 176 }}>
          <div className={"banner " + (sheet.scale === "none" ? "banner--missing" : "banner--attention")}>
            <div style={{ flex: 1 }}>
              <strong>{sheet.scale === "none" ? "Missing scale" : "Scale needs confirmation"}</strong>
              <p>
                {sheet.scale === "none"
                  ? `${sheet.number} has no scale label, so measured items on this sheet are estimates only. Set the scale or calibrate against a known dimension.`
                  : `${sheet.number} shows two scale labels, so measured conduit lengths may be incorrect. Select the scale for the warehouse plan before approving its measured items.`}
              </p>
            </div>
            <button
              className="btn"
              style={{ flex: "0 0 auto" }}
              onClick={() => window.dispatchEvent(new CustomEvent("open-scale"))}
            >
              {sheet.scale === "none" ? "Set scale" : "Confirm scale"}
            </button>
          </div>
        </div>
      )}

      {tool === "calibrate" && (
        <div className="overlay" style={{ top: 14, left: "50%", transform: "translateX(-50%)" }}>
          <div className="banner" style={{ borderColor: "var(--blue-line)", borderLeft: "3px solid var(--blue)", borderRadius: "0 6px 6px 0" }}>
            <div>
              <strong>Calibrating</strong>
              <p>
                {calibPoints.length === 0
                  ? "Click the first end of a dimension you know."
                  : "Now click the other end."}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* legend */}
      {layers.legend && (
        <div className="overlay legend" style={{ left: 14, bottom: 14 }}>
          <h4>Review status</h4>
          {["missing", "attention", "ready", "approved"].map((k) => (
            <div className="legend__row" key={k}>
              <span className="swatch" style={{ background: STATUS[k].color, color: STATUS[k].color }} />
              {STATUS[k].label}
            </div>
          ))}
          <h4 style={{ marginTop: 9 }}>Overlay</h4>
          <div className="legend__row">
            <svg width="16" height="10">
              <line x1="0" y1="5" x2="16" y2="5" stroke="#b0322a" strokeWidth="2.4" strokeDasharray="5 3" />
            </svg>
            Unverified measurement
          </div>
          <div className="legend__row">
            <svg width="16" height="12">
              <circle cx="8" cy="6" r="5" fill="#9c5f06" />
              <text x="8" y="6" fill="#fff" fontSize="7" fontWeight="700" textAnchor="middle" dominantBaseline="central">
                !
              </text>
            </svg>
            Item has a warning
          </div>
        </div>
      )}

      {/* minimap */}
      <div className="overlay minimap" style={{ right: 14, bottom: 14 }}>
        <div className="minimap__frame" style={{ width: 136, height: 136 * (SHEET_H / SHEET_W) }}>
          {visible.map((it) => {
            const px = it.path ? it.path[0][0] : it.x;
            const py = it.path ? it.path[0][1] : it.y;
            return (
              <span
                key={it.id}
                className="minimap__dot"
                style={{
                  left: (px / SHEET_W) * 100 + "%",
                  top: (py / SHEET_H) * 100 + "%",
                  background: STATUS[it.status].color,
                }}
              />
            );
          })}
          <div
            className="minimap__view"
            style={{
              left: clamp((-view.tx / view.scale / SHEET_W) * 100, 0, 100) + "%",
              top: clamp((-view.ty / view.scale / SHEET_H) * 100, 0, 100) + "%",
              width: clamp((size.w / view.scale / SHEET_W) * 100, 0, 100) + "%",
              height: clamp((size.h / view.scale / SHEET_H) * 100, 0, 100) + "%",
            }}
          />
        </div>
      </div>
    </div>
  );
}
