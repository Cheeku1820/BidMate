"""The price request an estimator sends a supplier, and the parser
that reads the filled sheet back (estimate-first-pricing §6). Pure:
bytes in, records out. Only two cells are interpreted -- the price (a
number) and the row key (an id the caller checks belongs to the
project). Everything else is text, carried as text."""
from __future__ import annotations

import csv
import io
import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

import openpyxl
from openpyxl.utils import get_column_letter

HEADER = ("Item", "Description", "Qty", "Unit", "Unit price", "Supplier part no.", "Lead time (weeks)", "Notes", "Row key")
REQUIRED_HEADER = ("Item", "Unit price")
_KEY_COL = HEADER.index("Row key") + 1
# A leading or trailing currency word ("USD 9.10", "9.10 USD"), stripped
# before the number itself is validated.
_CURRENCY_WORD_LEAD_RE = re.compile(r"^[A-Za-z]+\s+")
_CURRENCY_WORD_TRAIL_RE = re.compile(r"\s+[A-Za-z]+$")
# US-style thousands grouping ("2,250.00") -- the comma is only ever
# removed once the grouping itself is confirmed correct, never blindly,
# so a European "2.250,00" (which is a different number, not a
# formatting variant) is refused rather than silently mis-parsed.
_THOUSANDS_RE = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")
# A unit price is zero or more and below this: the column it lands in
# (ProjectMaterialPrice.price_override, Numeric(10, 2)) holds up to
# 99,999,999.99, and a negative price is a typo that would subtract
# from the bid. Either reads back as unpriced, never as a number.
PRICE_LIMIT = Decimal("100000000")


def price_in_range(value: Decimal) -> bool:
    return Decimal(0) <= value < PRICE_LIMIT


class ParsedRow(NamedTuple):
    row_key: str | None
    item_name: str
    unit_price: Decimal | None
    part_no: str
    notes: str
    line: int
    # The supplier's own lead time, in whole weeks (phases-and-timeline
    # §7.1). Optional: a sheet from before the column existed, or a
    # supplier who left it blank, parses exactly as it always did.
    lead_weeks: int | None = None
    lead_error: str | None = None


class ParsedSheet(NamedTuple):
    rows: list[ParsedRow]
    refused: str | None


def build_request_workbook(rows: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Price request"
    ws.append(list(HEADER))
    for r in rows:
        # Positional against HEADER: every blank the supplier fills in
        # (price, part number, lead time, notes) is None here, and the
        # row key is last. Built by length so adding a column to HEADER
        # cannot silently shift the key into the wrong cell.
        blanks = [None] * (len(HEADER) - 5)
        ws.append([r["item_name"], (r.get("description") or "").splitlines()[0] if r.get("description") else "",
                   r["quantity"], r["unit"], *blanks, str(r["item_id"])])
    ws.column_dimensions[get_column_letter(_KEY_COL)].hidden = True
    for col, width in zip("ABCDEFGH", (36, 48, 8, 8, 14, 20, 16, 30)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _price(v) -> Decimal | None:
    """The one cell besides the row key that's interpreted rather than
    carried as text -- so a wrong number here is the failure this
    module exists to prevent. A number (int/float/Decimal, but not
    bool: `True`/`False` are never a price) converts directly. A string
    is accepted only when, after stripping a `$`, surrounding
    whitespace, and a leading or trailing currency word, what remains
    is unambiguously a plain or US-grouped decimal number -- scientific
    notation ("1e3"), a European "2.250,00", "call for price", or
    anything else non-numeric returns None (unpriced) rather than
    guessing. So does a number outside `price_in_range`: a negative
    price or one the price column can't hold is listed as unpriced,
    not carried to the apply step to fail there."""
    if isinstance(v, bool):
        return None
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        try:
            d = Decimal(str(v)).quantize(Decimal("0.01"))
        except InvalidOperation:   # inf, nan
            return None
        return d if price_in_range(d) else None
    s = str(v).strip()
    s = _CURRENCY_WORD_LEAD_RE.sub("", s)
    s = _CURRENCY_WORD_TRAIL_RE.sub("", s)
    s = s.replace("$", "").strip()
    if _THOUSANDS_RE.match(s):
        s = s.replace(",", "")
    elif not _PLAIN_NUMBER_RE.match(s):
        return None
    try:
        d = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return d if price_in_range(d) else None


# A lead time is a whole number of weeks. "12 wks" is a person writing
# a unit into a number column, not a number -- it is named back to them
# by row rather than guessed at or dropped.
_LEAD_RE = re.compile(r"^\s*(\d{1,3})\s*$")


def _lead(cell, line: int) -> tuple[int | None, str | None]:
    if cell is None or str(cell).strip() == "":
        return None, None
    if isinstance(cell, bool):
        return None, f"Row {line}: the lead time isn't a number of weeks"
    if isinstance(cell, (int, float)) and float(cell).is_integer() and 0 <= float(cell) < 1000:
        return int(cell), None
    match = _LEAD_RE.match(str(cell))
    if match:
        return int(match.group(1)), None
    return None, f"Row {line}: the lead time isn't a number of weeks"


def _grid(data: bytes, filename: str) -> list[list]:
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    try:
        ws = wb.active
        return [list(row) for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _find_header(grid: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, row in enumerate(grid[:20]):
        names = {str(c).strip().lower(): j for j, c in enumerate(row) if c is not None and str(c).strip()}
        if all(h.lower() in names for h in REQUIRED_HEADER):
            return i, names
    return None


def parse_price_sheet(data: bytes, filename: str) -> ParsedSheet:
    try:
        grid = _grid(data, filename)
    except Exception:
        return ParsedSheet([], "This file couldn't be read as a spreadsheet. Upload the .xlsx or .csv the price request was sent as.")
    found = _find_header(grid)
    if found is None:
        return ParsedSheet([], f"The sheet needs a header row with the columns {' and '.join(REQUIRED_HEADER)}. "
                               f"The price request download has them in place.")
    hi, cols = found
    rows: list[ParsedRow] = []
    for n, row in enumerate(grid[hi + 1:], start=hi + 2):
        def cell(name):
            j = cols.get(name.lower())
            return row[j] if j is not None and j < len(row) else None
        name = cell("Item")
        if name is None or not str(name).strip():
            continue
        key = cell("Row key")
        lead_weeks, lead_error = _lead(cell("Lead time (weeks)"), n)
        rows.append(ParsedRow(
            row_key=str(key).strip() if key not in (None, "") else None,
            item_name=str(name).strip(),
            unit_price=_price(cell("Unit price")),
            part_no=str(cell("Supplier part no.") or "").strip()[:100],
            notes=str(cell("Notes") or "").strip()[:500],
            line=n,
            lead_weeks=lead_weeks,
            lead_error=lead_error,
        ))
    return ParsedSheet(rows, None)
