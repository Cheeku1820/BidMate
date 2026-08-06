/* ============================================================
   Symbols.jsx — takeoff markers drawn as electrical symbols.

   Each glyph is drawn centred on (0,0) in a nominal 26-unit box so
   markers read as drafting symbols rather than generic dots. Status
   is carried by the halo ring AND the glyph shape AND the panel
   label — never by hue alone.
   ============================================================ */

export function SymbolGlyph({ kind, color, size = 26 }) {
  const s = size / 26;
  const stroke = { stroke: color, strokeWidth: 1.9 / s, fill: "none", vectorEffect: "non-scaling-stroke" };
  const text = {
    fill: color,
    fontSize: 11,
    fontWeight: 700,
    textAnchor: "middle",
    dominantBaseline: "central",
    fontFamily: "Inter, sans-serif",
  };

  switch (kind) {
    case "receptacle":
      return (
        <g>
          <circle r="8" fill="#fff" {...stroke} />
          <line x1="-8" y1="0" x2="8" y2="0" {...stroke} />
          <line x1="0" y1="0" x2="0" y2="-8" {...stroke} />
        </g>
      );
    case "switch":
      return (
        <g>
          <circle r="8" fill="#fff" {...stroke} />
          <text {...text}>S</text>
        </g>
      );
    case "panel":
      return (
        <g>
          <rect x="-11" y="-7" width="22" height="14" fill="#fff" {...stroke} />
          <line x1="-11" y1="-7" x2="11" y2="7" {...stroke} />
          <line x1="-11" y1="7" x2="11" y2="-7" {...stroke} />
        </g>
      );
    case "highbay":
      return (
        <g>
          <circle r="9" fill="#fff" {...stroke} />
          <line x1="-6.4" y1="-6.4" x2="6.4" y2="6.4" {...stroke} />
          <line x1="-6.4" y1="6.4" x2="6.4" y2="-6.4" {...stroke} />
        </g>
      );
    case "troffer":
      return (
        <g>
          <rect x="-13" y="-6.5" width="26" height="13" fill="#fff" {...stroke} />
          <line x1="-13" y1="0" x2="13" y2="0" {...stroke} />
        </g>
      );
    case "exit":
      return (
        <g>
          <rect x="-10" y="-7" width="20" height="14" fill="#fff" {...stroke} />
          <line x1="-10" y1="-7" x2="10" y2="7" {...stroke} />
          <line x1="-10" y1="7" x2="10" y2="-7" {...stroke} />
          <line x1="0" y1="-7" x2="0" y2="7" {...stroke} />
        </g>
      );
    case "disconnect":
      return (
        <g>
          <rect x="-8" y="-8" width="16" height="16" fill="#fff" {...stroke} />
          <line x1="-5" y1="5" x2="5" y2="-5" {...stroke} />
        </g>
      );
    case "junction":
      return (
        <g>
          <rect x="-8" y="-8" width="16" height="16" fill="#fff" {...stroke} />
          <text {...text}>J</text>
        </g>
      );
    case "data":
      return (
        <g>
          <path d="M0,-9 L9,6 L-9,6 Z" fill="#fff" {...stroke} />
          <text {...text} y="1.5" style={{ fontSize: 8 }}>
            D
          </text>
        </g>
      );
    case "unknown":
      return (
        <g>
          <circle r="9" fill="#fff" {...stroke} strokeDasharray="3 2.4" />
          <text {...text}>?</text>
        </g>
      );
    case "run":
    default:
      return <circle r="6" fill="#fff" {...stroke} />;
  }
}

export const SYMBOL_LABELS = {
  receptacle: "Receptacle",
  switch: "Switch",
  panel: "Panel",
  highbay: "High-bay fixture",
  troffer: "Troffer fixture",
  exit: "Exit sign",
  disconnect: "Disconnect",
  junction: "Junction box",
  data: "Data outlet",
  unknown: "Unclassified",
  run: "Conduit run",
};
