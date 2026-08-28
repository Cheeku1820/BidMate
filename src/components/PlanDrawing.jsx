/* ============================================================
   PlanDrawing.jsx — the drawing underneath the takeoff.

   Not a placeholder rectangle: each sheet is drafted with double-line
   walls, a column grid with bubbles, door swings, dimension strings,
   room tags, a north arrow, a graphic scale, and a title block with a
   revision triangle. The takeoff markers sit on top of real geometry,
   which is what makes the review workspace feel like a drawing set
   rather than a chart.

   Sheet space is 1000 x 750 units for every plan.
   ============================================================ */

const WALL = "#6e6a62";
const THIN = "#b8b3a9";
const DIM = "#8a857c";
const TEXT = "#5f5b54";

function GridBubble({ x, y, label }) {
  return (
    <g>
      <circle cx={x} cy={y} r="13" fill="#fdfcf9" stroke={DIM} strokeWidth="1.1" />
      <text x={x} y={y} fill={TEXT} fontSize="12" fontWeight="600" textAnchor="middle" dominantBaseline="central">
        {label}
      </text>
    </g>
  );
}

function DimString({ x1, y1, x2, y2, label, offset = 0, vertical = false }) {
  const tx = vertical ? x1 - 10 : (x1 + x2) / 2;
  const ty = vertical ? (y1 + y2) / 2 : y1 - 6;
  return (
    <g stroke={DIM} strokeWidth="0.8" fill="none">
      <line x1={x1} y1={y1} x2={x2} y2={y2} />
      <line x1={x1} y1={vertical ? y1 : y1 - 5} x2={vertical ? x1 + 5 : x1} y2={vertical ? y1 : y1 + 5} />
      <line x1={vertical ? x2 - 5 : x2} y1={vertical ? y2 : y2 - 5} x2={x2} y2={vertical ? y2 : y2 + 5} />
      <text
        x={tx + (vertical ? -offset : 0)}
        y={ty}
        fill={TEXT}
        fontSize="10.5"
        textAnchor="middle"
        stroke="none"
        transform={vertical ? `rotate(-90 ${tx} ${ty})` : undefined}
      >
        {label}
      </text>
    </g>
  );
}

function RoomTag({ x, y, name, number }) {
  return (
    <g>
      <text x={x} y={y} fill={TEXT} fontSize="12" fontWeight="600" textAnchor="middle">
        {name}
      </text>
      <text x={x} y={y + 14} fill={DIM} fontSize="10.5" textAnchor="middle">
        {number}
      </text>
    </g>
  );
}

function DoorSwing({ x, y, size = 30, rotate = 0 }) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${rotate})`} stroke={WALL} strokeWidth="1.2" fill="none">
      <line x1="0" y1="0" x2="0" y2={-size} />
      <path d={`M0,${-size} A ${size} ${size} 0 0 1 ${size} 0`} strokeWidth="0.8" stroke={THIN} />
    </g>
  );
}

function NorthArrow({ x, y }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <circle r="20" fill="none" stroke={DIM} strokeWidth="0.9" />
      <path d="M0,-15 L6,9 L0,3 L-6,9 Z" fill={TEXT} />
      <text y="-24" fill={TEXT} fontSize="11" fontWeight="700" textAnchor="middle">
        N
      </text>
    </g>
  );
}

function GraphicScale({ x, y, label }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={i * 22} y="0" width="22" height="6" fill={i % 2 ? "#fdfcf9" : TEXT} stroke={TEXT} strokeWidth="0.7" />
      ))}
      <text x="0" y="18" fill={TEXT} fontSize="9.5">
        0
      </text>
      <text x="88" y="18" fill={TEXT} fontSize="9.5" textAnchor="end">
        40'
      </text>
      <text x="0" y="-5" fill={TEXT} fontSize="9.5">
        {label}
      </text>
    </g>
  );
}

function TitleBlock({ sheet }) {
  const scaleText = sheet.scale === "none" ? "SCALE: —" : sheet.scale === "mixed" ? "SCALE: AS NOTED" : sheet.scale === "nts" ? "SCALE: NTS" : `SCALE: ${sheet.scale}`;
  return (
    <g>
      <rect x="700" y="648" width="278" height="80" fill="#fdfcf9" stroke={WALL} strokeWidth="1.2" />
      <line x1="700" y1="676" x2="978" y2="676" stroke={THIN} strokeWidth="0.9" />
      <line x1="700" y1="702" x2="978" y2="702" stroke={THIN} strokeWidth="0.9" />
      <line x1="884" y1="702" x2="884" y2="728" stroke={THIN} strokeWidth="0.9" />
      <text x="710" y="667" fill={TEXT} fontSize="11.5" fontWeight="600">
        MERIDIAN DISTRIBUTION CENTER
      </text>
      <text x="710" y="693" fill={TEXT} fontSize="10.5">
        {sheet.title.toUpperCase()}
      </text>
      <text x="710" y="720" fill={TEXT} fontSize="10.5">
        {scaleText}
      </text>
      <text x="894" y="720" fill={TEXT} fontSize="14" fontWeight="700">
        {sheet.number}
      </text>
      <g transform="translate(958 660)">
        <path d="M0,-9 L9,7 L-9,7 Z" fill="none" stroke={TEXT} strokeWidth="1" />
        <text y="3" fill={TEXT} fontSize="9" fontWeight="700" textAnchor="middle">
          {sheet.revision.replace("Rev ", "")}
        </text>
      </g>
    </g>
  );
}

/* ---------------------------------------------------------------- */

function WarehousePlan({ sheet }) {
  const cols = [
    { x: 150, l: "A" },
    { x: 340, l: "B" },
    { x: 530, l: "C" },
    { x: 720, l: "D" },
    { x: 890, l: "E" },
  ];
  const rows = [
    { y: 150, l: "1" },
    { y: 340, l: "2" },
    { y: 530, l: "3" },
  ];
  return (
    <g>
      <rect x="110" y="110" width="820" height="500" fill="#fdfcf9" stroke={WALL} strokeWidth="3" />
      <rect x="118" y="118" width="804" height="484" fill="none" stroke={WALL} strokeWidth="1.2" />

      {cols.map((c) => (
        <g key={c.l}>
          <line x1={c.x} y1="86" x2={c.x} y2="610" stroke={THIN} strokeWidth="0.7" strokeDasharray="14 5 3 5" />
          <GridBubble x={c.x} y={72} label={c.l} />
        </g>
      ))}
      {rows.map((r) => (
        <g key={r.l}>
          <line x1="86" y1={r.y} x2="930" y2={r.y} stroke={THIN} strokeWidth="0.7" strokeDasharray="14 5 3 5" />
          <GridBubble x={72} y={r.y} label={r.l} />
        </g>
      ))}
      {cols.map((c) =>
        rows.map((r) => <rect key={c.l + r.l} x={c.x - 7} y={r.y - 7} width="14" height="14" fill={WALL} opacity="0.5" />)
      )}

      {/* dock office, enclosed */}
      <rect x="640" y="380" width="220" height="150" fill="#f4f2ec" stroke={WALL} strokeWidth="2" />
      <DoorSwing x={700} y={530} size={28} rotate={0} />
      <RoomTag x={760} y={440} name="DOCK OFFICE" number="118" />

      {/* dock doors along the east wall */}
      {[180, 270, 360].map((y) => (
        <g key={y}>
          <rect x="922" y={y} width="16" height="62" fill="#fdfcf9" stroke={WALL} strokeWidth="1.4" />
          <line x1="922" y1={y} x2="938" y2={y + 62} stroke={THIN} strokeWidth="0.7" />
        </g>
      ))}
      <text x="946" y="252" fill={TEXT} fontSize="10.5" transform="rotate(90 946 252)">
        LOADING DOCK
      </text>

      {/* slab hatch in open warehouse */}
      <g opacity="0.45">
        {Array.from({ length: 14 }).map((_, i) => (
          <line key={i} x1={130 + i * 36} y1="118" x2={130 + i * 36} y2="602" stroke="#e8e5dd" strokeWidth="0.6" />
        ))}
      </g>

      <RoomTag x={370} y={250} name="OPEN WAREHOUSE" number="100" />
      <DimString x1={110} y1={92} x2={930} y2={92} label="240'-0&quot;" />
      <DimString x1={96} y1={110} x2={96} y2={610} label="150'-0&quot;" vertical />
      <NorthArrow x={946} y={130} />
      <GraphicScale x={130} y={640} label={sheet.scale === "mixed" ? 'PLAN SCALE: 1/8" = 1\'-0" (SEE NOTE)' : "PLAN SCALE"} />
      <text x="130" y="672" fill="#a03a2f" fontSize="10">
        NOTE: ENLARGED DOCK PLAN DRAWN AT 1/16" = 1'-0"
      </text>
      <TitleBlock sheet={sheet} />
    </g>
  );
}

function OfficePlan({ sheet }) {
  return (
    <g>
      <rect x="140" y="120" width="740" height="470" fill="#fdfcf9" stroke={WALL} strokeWidth="3" />
      <rect x="148" y="128" width="724" height="454" fill="none" stroke={WALL} strokeWidth="1.2" />

      {/* corridor spine */}
      <line x1="148" y1="360" x2="872" y2="360" stroke={WALL} strokeWidth="2" />
      <line x1="148" y1="410" x2="872" y2="410" stroke={WALL} strokeWidth="2" />
      <RoomTag x={510} y={392} name="CORRIDOR" number="150" />

      {/* north offices */}
      {[
        [148, 300, "OFFICE", "151"],
        [300, 300, "OFFICE", "152"],
        [452, 300, "CONFERENCE", "153"],
      ].map(([x, w, n, num]) => (
        <g key={num}>
          <line x1={x + w} y1="128" x2={x + w} y2="360" stroke={WALL} strokeWidth="2" />
          <RoomTag x={x + w / 2} y={230} name={n} number={num} />
          <DoorSwing x={x + w / 2} y={360} size={26} rotate={180} />
        </g>
      ))}
      <RoomTag x={752} y={230} name="BREAK ROOM" number="154" />

      {/* south open office with ceiling grid */}
      <g opacity="0.5">
        {Array.from({ length: 15 }).map((_, i) => (
          <line key={"v" + i} x1={168 + i * 48} y1="410" x2={168 + i * 48} y2="582" stroke="#e2ded5" strokeWidth="0.6" />
        ))}
        {Array.from({ length: 4 }).map((_, i) => (
          <line key={"h" + i} x1="148" y1={434 + i * 48} x2="872" y2={434 + i * 48} stroke="#e2ded5" strokeWidth="0.6" />
        ))}
      </g>
      <RoomTag x={420} y={520} name="OPEN OFFICE" number="155" />

      <line x1="620" y1="410" x2="620" y2="582" stroke={WALL} strokeWidth="2" />
      <RoomTag x={748} y={500} name="STORAGE" number="156" />
      <DoorSwing x={620} y={470} size={26} rotate={90} />

      <DimString x1={140} y1={104} x2={880} y2={104} label="185'-0&quot;" />
      <DimString x1={124} y1={120} x2={124} y2={590} label="118'-0&quot;" vertical />
      <NorthArrow x={920} y={140} />
      <GraphicScale x={150} y={624} label="PLAN SCALE: NOT LABELED" />
      <text x="150" y="656" fill="#a03a2f" fontSize="10">
        NO SCALE FOUND IN TITLE BLOCK
      </text>
      <TitleBlock sheet={sheet} />
    </g>
  );
}

/** The base layer for a sheet whose drawing is a rendered page from an
 *  uploaded document. Deliberately empty: the estimator's markers sit
 *  over the real page image, and if that image is slow or fails to load
 *  what shows through must be blank paper, never invented geometry. A
 *  fabricated plan under a real takeoff would read as the estimator's
 *  own drawing. The only text here comes from the sheet record itself. */
function IngestedSheetSurface({ sheet }) {
  return (
    <g>
      <text x="500" y="374" fill={DIM} fontSize="12" textAnchor="middle">
        {sheet.number}
        {sheet.title ? ` — ${sheet.title}` : ""}
      </text>
    </g>
  );
}

export default function PlanDrawing({ sheet }) {
  if (sheet.plan === "warehouse") return <WarehousePlan sheet={sheet} />;
  if (sheet.plan === "office") return <OfficePlan sheet={sheet} />;
  // Anything else — every sheet that came from an uploaded document —
  // gets the neutral surface. There is no drawn geometry that could
  // honestly stand in for a page nobody in this codebase has seen.
  return <IngestedSheetSurface sheet={sheet} />;
}
