import { Search, Check, ChevronLeft, ChevronRight } from "lucide-react";
import { STATUS } from "../lib/vocabulary.js";
import { displayStatus } from "./Pill.jsx";

const FILTERS = [
  ["all", "All"],
  ["electrical", "Electrical"],
  ["attention", "Needs attention"],
  ["reviewed", "Reviewed"],
];

/** Left panel: documents and sheets (spec §5, screen F). Filters and
 *  search operate on sheets; each row's thumbnail dots and warning
 *  count are drawn straight from that sheet's items. */
export default function SheetsRail({ sheets, items, sheetId, onSelectSheet, filter, onFilter, query, onQuery, open, onToggleOpen }) {
  const sheetsShown = sheets.filter((s) => {
    if (query && !(s.number + " " + s.title).toLowerCase().includes(query.toLowerCase())) return false;
    const its = items.filter((i) => i.sheetId === s.id);
    if (filter === "electrical") return s.discipline === "Electrical";
    if (filter === "attention") return its.some((i) => !i.rejected && (i.status === "attention" || i.status === "missing"));
    if (filter === "reviewed") return its.length > 0 && its.every((i) => i.status === "approved" || i.rejected);
    return true;
  });

  return (
    <nav className={"sheets" + (open ? "" : " sheets--collapsed")} aria-label="Sheets">
      {open && (
        <>
          <div className="sheets__head">
            <div className="search">
              <Search size={14} color="var(--ink-3)" />
              <input value={query} onChange={(e) => onQuery(e.target.value)} placeholder="Search sheets" aria-label="Search sheets" />
            </div>
          </div>
          <div className="chips">
            {FILTERS.map(([k, l]) => (
              <button key={k} className="chip" aria-pressed={filter === k} onClick={() => onFilter(k)}>{l}</button>
            ))}
          </div>
          <div className="sheetlist">
            {sheetsShown.map((s) => {
              const its = items.filter((i) => i.sheetId === s.id);
              const warn = its.filter((i) => i.warnings?.length).length;
              const done = its.length > 0 && its.every((i) => i.status === "approved" || i.rejected);
              return (
                <button key={s.id} className="sheetrow" aria-current={s.id === sheetId} onClick={() => onSelectSheet(s.id)}>
                  <span className="sheetrow__thumb">
                    <svg viewBox="0 0 1000 750" width="100%" height="100%">
                      <rect x="80" y="80" width="840" height="520" fill="none" stroke="#c2beb4" strokeWidth="26" />
                      {its.slice(0, 6).map((i) => (
                        <circle key={i.id} cx={i.path ? i.path[0][0] : i.x} cy={i.path ? i.path[0][1] : i.y} r="34" fill={STATUS[displayStatus(i)].color} />
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
        <button className="iconbtn" onClick={onToggleOpen} aria-label={open ? "Collapse sheet list" : "Expand sheet list"}>
          {open ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>
    </nav>
  );
}
