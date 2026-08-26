import { AlertTriangle, AlertCircle, CheckCircle2, Circle, CircleSlash } from "lucide-react";
import { STATUS } from "../lib/data.js";

const STATUS_ICON = { ready: Circle, attention: AlertTriangle, missing: AlertCircle, approved: CheckCircle2, rejected: CircleSlash };

/** Status is never color alone (CLAUDE.md): hue, icon, and text label
 *  together, every time a status appears anywhere in the workspace. */
export default function Pill({ status }) {
  const Icon = STATUS_ICON[status];
  return (
    <span className={"pill pill--" + status}>
      <Icon size={12} strokeWidth={2.6} />
      {STATUS[status].label}
    </span>
  );
}

/** `rejected` is a boolean field on an item, never a fifth review
 *  status (task-16-brief.md §3) — the API and both stores keep it
 *  separate from `status` on purpose. This is the one place that
 *  separation gets folded back into a single display value, for the
 *  Pill/marker/thumbnail treatments that predate that split and still
 *  render "Rejected" as if it were a fifth status color. */
export function displayStatus(item) {
  return item.rejected ? "rejected" : item.status;
}
