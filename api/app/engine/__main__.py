"""CLI: run the takeoff engine on a PDF and print the estimate.

    python -m app.engine <drawings.pdf> [labor_rate]

Prints the detected sheets, the priced item takeoff, and the total direct
cost -- the whole "blueprint in, estimate out" loop on the command line,
before any of it is wired into the app.
"""

from __future__ import annotations

import sys

from . import pipeline
from .pricing import DEFAULT_LABOR_RATE


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python -m app.engine <drawings.pdf> [labor_rate]", file=sys.stderr)
        return 2
    path = sys.argv[1]
    rate = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LABOR_RATE
    result = pipeline.run(path, rate)

    read = [s for s in result.sheets if not s.unreadable_reason]
    unread = [s for s in result.sheets if s.unreadable_reason]
    print(f"Electrical sheets: {len(result.sheets)} detected, {len(read)} read, {len(unread)} unreadable")
    for s in unread:
        print(f"  ! {s.number or 'page ' + str(s.page_index + 1)}: {s.unreadable_reason}")

    print(f"\n{'item':<34}{'qty':>5}  {'status':<11}{'material':>10}{'hours':>7}{'total':>11}")
    print("-" * 82)
    for p in sorted(result.items, key=lambda p: p.total_direct_cost, reverse=True):
        it = p.item
        print(f"{it.name[:33]:<34}{it.quantity:>5}  {it.status:<11}"
              f"{'$' + format(p.material_cost, ',.0f'):>10}{p.labor_hours:>7.1f}{'$' + format(p.total_direct_cost, ',.0f'):>11}")

    flagged = [p for p in result.items if p.item.status != "ready"]
    print("-" * 82)
    print(f"Items: {len(result.items)}  ({len(flagged)} need attention before approval)")
    print(f"Material:            ${result.material_total:>12,.2f}")
    print(f"Labor:  {result.labor_hours_total:>8,.1f} hrs @ ${result.labor_rate:.0f}  ${result.labor_cost_total:>12,.2f}")
    print(f"TOTAL DIRECT COST:   ${result.total_direct_cost:>12,.2f}")
    print("(markup, overhead, and profit are the estimator's layer — not included)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
