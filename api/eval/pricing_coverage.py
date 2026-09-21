"""Coverage of the two market sources against the firm's own bid lines
(estimate-first-pricing §10). Reads the two estimate workbooks in
bid_examples/, routes every per-unit Division 26 line as the price job
would, calls both sources for the given ZIP, and writes a table to
bid_examples/_derived/pricing_coverage.md (gitignored -- a firm's
prices stay out of git). --dry-run routes without calling anything.

    cd api && python -m eval.pricing_coverage --zip 78701
"""
from __future__ import annotations

import argparse
import glob
import os
import statistics
from decimal import Decimal

from app.market.classify import classify_for_lookup

CORPUS = os.path.join(os.path.dirname(__file__), "..", "..", "bid_examples")
OUT = os.path.join(CORPUS, "_derived", "pricing_coverage.md")


def classify_lines(lines: list[dict]) -> dict[str, int]:
    counts = {"lines": len(lines), "onebuild": 0, "shopping": 0, "quote_required": 0}
    for ln in lines:
        lk = classify_for_lookup(ln["name"], ln.get("description", ""), ln["unit"])
        counts[lk.source or "quote_required"] += 1
    return counts


def read_lines() -> list[dict]:
    import openpyxl
    files = glob.glob(os.path.join(CORPUS, "FedEx Office Bid", "*.xlsx")) + glob.glob(os.path.join(CORPUS, "Gerber*", "*.xlsx"))
    out, seen = [], set()
    for f in files:
        wb = openpyxl.load_workbook(f, data_only=True, read_only=True)
        for ws in wb.worksheets:
            if ws.title.upper().startswith("SUMMARY"):
                continue
            hdr = None
            section = ""
            for row in ws.iter_rows(values_only=True):
                vals = [str(v).strip() if v is not None else "" for v in row]
                if hdr is None:
                    if "DESCRIPTION" in vals and "QTY." in vals:
                        hdr = {n: i for i, n in enumerate(vals)}
                    continue
                csi, desc, qty = vals[hdr["CSI NO."]], vals[hdr["DESCRIPTION"]], vals[hdr["QTY."]]
                if csi and not qty:
                    section = csi[:2]
                    continue
                if not desc or not qty or section != "26" or desc.lower() == "sub total" or desc in seen:
                    continue
                seen.add(desc)
                first, _, rest = desc.partition("\n")
                um = vals[hdr["UNIT MATERIAL COST"]] if "UNIT MATERIAL COST" in hdr else ""
                out.append({"name": first, "description": rest, "unit": vals[hdr["UNIT"]],
                            "unit_material": float(um) if um else None})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default="78701")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    lines = read_lines()
    counts = classify_lines(lines)
    rows, priced = [], {"onebuild": 0, "shopping": 0, "no_match": 0, "failed": 0}
    if not args.dry_run:
        from app.worker.market_sources import SourceError, get_sources
        sources = get_sources()

        class P:
            location, postal_code = f"Austin, TX {args.zip}", args.zip
        for ln in lines:
            lk = classify_for_lookup(ln["name"], ln["description"], ln["unit"])
            if lk.source is None or lk.source not in sources:
                continue
            src = sources[lk.source]
            try:
                res = src.lookup(lk.query, ln["unit"], src.location_key(P()))
            except SourceError:
                priced["failed"] += 1
                continue
            if res.status != "priced":
                priced["no_match"] += 1
                continue
            priced[lk.source] += 1
            ratio = (float(res.unit_price) / ln["unit_material"]) if ln["unit_material"] else None
            rows.append((ln["name"][:50], lk.source, ln["unit_material"], float(res.unit_price), ratio))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write(f"# Pricing coverage, ZIP {args.zip}\n\n")
        fh.write("| Lines | Routed to 1build | Routed to shopping | Quote required | Priced by 1build | Priced by shopping | No match | Failed |\n|---|---|---|---|---|---|---|---|\n")
        fh.write(f"| {counts['lines']} | {counts['onebuild']} | {counts['shopping']} | {counts['quote_required']} | "
                 f"{priced['onebuild']} | {priced['shopping']} | {priced['no_match']} | {priced['failed']} |\n\n")
        if rows:
            ratios = [r[4] for r in rows if r[4]]
            fh.write(f"Median market / firm ratio: {statistics.median(ratios):.2f}\n\n" if ratios else "")
            fh.write("| Line | Source | Firm unit cost | Market | Ratio |\n|---|---|---|---|---|\n")
            for name, src, firm, market, ratio in rows:
                fh.write(f"| {name} | {src} | {firm} | {market:.2f} | {f'{ratio:.2f}' if ratio else ''} |\n")
    print(open(OUT).read())


if __name__ == "__main__":
    main()
