import { ChevronUp, ChevronDown } from "lucide-react";

/** Bottom summary drawer (spec §5, screen F). The collapsed strip's
 *  five stats come straight off `totals` — the one place totals are
 *  computed (ROADMAP.md invariant 1) — never re-derived here. The
 *  expanded per-system panel is a completeness view (how many of each
 *  system's items are approved), a different, purely local aggregation
 *  that totals.by_system (approved quantity, not item count) does not
 *  provide. */
export default function SummaryDrawer({ totals, bySystem, open, onToggle }) {
  return (
    <div className="drawer">
      <button className="drawer__strip" onClick={onToggle} aria-expanded={open}>
        <span className="stat"><b className="tabular">{totals.approvedCount}</b><span>Approved</span></span>
        <span className="stat"><b className="tabular">{totals.remainingCount}</b><span>Remaining</span></span>
        <span className="stat"><b className="tabular" style={{ color: totals.attentionCount ? "var(--amber)" : undefined }}>{totals.attentionCount}</b><span>Needs attention</span></span>
        <span className="stat"><b className="tabular" style={{ color: totals.missingCount ? "var(--red)" : undefined }}>{totals.missingCount}</b><span>Missing information</span></span>
        <span className="stat"><b className="tabular">{totals.approvedUnits.toLocaleString()}</b><span>Approved units</span></span>
        <span className="spacer" />
        <span style={{ fontSize: 12, color: "var(--ink-3)", display: "flex", alignItems: "center", gap: 5 }}>
          {open ? "Hide totals" : "System totals"} {open ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        </span>
      </button>
      {open && (
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
  );
}
