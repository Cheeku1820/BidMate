/* ============================================================
   seed-ingest.js — maps the engine's /estimate/full payload into the
   store's sheet + item shape, so the real takeoff renders through the
   same review workspace, spreadsheet, drawer, and export the seed
   fixture uses.

   Each engine cluster becomes one reviewable item positioned on its
   sheet (x,y in PDF points, with the full placement list kept for the
   canvas). Cost fields ride along as extra properties the store passes
   through untouched -- the spreadsheet and export read them; nothing
   else has to know about them.
   ============================================================ */

// Map a catalog item name/system to one of the canvas's drawn glyph keys
// (Symbols.jsx). Unknown -> junction (a neutral box marker).
function inferSymbol(name, system) {
  const n = (name || "").toLowerCase();
  const sys = (system || "").toLowerCase();
  if (n.includes("gfci") || n.includes("receptacle") || (n.includes("outlet") && !n.includes("data"))) return "receptacle";
  if (n.includes("switch")) return "switch";
  if (n.includes("disconnect")) return "disconnect";
  if (n.includes("panel") || n.includes("board")) return "panel";
  if (n.includes("junction") || n.includes("box")) return "junction";
  if (n.includes("data") || n.includes("telecom") || n.includes("outlet") || sys.includes("low voltage")) return "data";
  if (n.includes("exit")) return "exit";
  if (n.includes("high bay") || n.includes("highbay")) return "highbay";
  if (n.includes("troffer") || n.includes("downlight") || n.includes("luminaire") || n.includes("fixture") || n.includes("light") || sys === "lighting") return "troffer";
  return "junction";
}

/** Maps the engine payload to `{ sheets, items }` in the store shape. */
export function mapPayload(payload) {
  const sheets = (payload.sheets || []).map((s, i) => ({
    id: `esheet-${i}`,
    number: s.number || `E${i + 1}`,
    title: "Electrical plan",
    discipline: "Electrical",
    revision: "",
    revisionDate: null,
    scale: "",
    scaleOptions: [],
    plan: "",
    superseded: false,
    // Section 6 uses these to place markers on the rendered page.
    widthPt: s.width_pt,
    heightPt: s.height_pt,
    pageIndex: s.page,
    unreadable: s.unreadable || null,
  }));
  const sheetIdByNumber = {};
  for (const s of sheets) sheetIdByNumber[s.number] = s.id;
  const fallbackSheet = sheets[0]?.id ?? null;

  const items = (payload.items || []).map((r) => ({
    id: crypto.randomUUID(),
    sheetId: sheetIdByNumber[r.sheet] ?? fallbackSheet,
    symbol: inferSymbol(r.name, r.system),
    name: r.name,
    description: "",
    system: r.system,
    category: r.category || "",
    quantity: r.quantity,
    unit: r.unit,
    status: r.status, // "ready" | "attention"
    x: r.x,
    y: r.y,
    placements: r.placements || [],
    rejected: false,
    warnings: r.warning ? [r.warning] : [],
    version: 1,
    // cost, carried through for the spreadsheet and export
    materialCost: r.material_cost ?? 0,
    laborHours: r.labor_hours ?? 0,
    laborCost: r.labor_cost ?? 0,
    totalCost: r.total_cost ?? 0,
  }));

  return { sheets, items };
}
