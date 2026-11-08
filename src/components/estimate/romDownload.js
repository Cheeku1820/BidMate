/* ============================================================
   romDownload.js — the ROM as a file the estimator can send.

   docs/specs/rom-estimate.md puts downloading the ROM on this
   workspace, deliberately NOT on Export: Export previews approved
   totals and blocks on Missing information, and a ROM has no approval
   step and no blocking gate. Two outputs, two paths, no shared gate.

   CSV rather than a styled document, matching Export's own current
   limitation — and every assumed line goes in the file, because a ROM
   whose download dropped the disclosures would be the bare number this
   whole feature exists to prevent handing over.
   ============================================================ */

export const ROM_COLUMNS = [
  "Section",
  "Line",
  "Origin",
  "Basis",
  "Quantity",
  "Unit",
  "Amount",
  "What was found",
  "Why it matters",
  "Where to look",
];

function sanitizeFileName(name) {
  return (
    (name || "estimate")
      .trim()
      .replace(/[^a-z0-9]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .toLowerCase() || "estimate"
  );
}

function escape(value) {
  const s = String(value ?? "");
  // Leading =, +, -, @ are formula triggers in Excel and Sheets. A
  // drawing set is untrusted input and its text reaches these cells, so
  // the same reasoning that keeps extracted text out of the prompt as
  // instruction keeps it out of a spreadsheet as a formula.
  const guarded = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
  return /[",\n\r]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
}

export function romFileName(estimate) {
  return `${sanitizeFileName(estimate?.projectName)}-rom-estimate.csv`;
}

export function toRomCsv(estimate) {
  const rows = [];

  for (const section of estimate.sections) {
    for (const line of section.lines) {
      rows.push([
        section.label,
        line.title,
        line.origin === "assumed" ? "Assumed" : "Counted",
        line.basisLabel || "",
        line.value || "",
        line.unit || "",
        // Blank, never 0, for a line nothing priced — the same
        // distinction the screen draws. A zero here would read as a
        // decision nobody made.
        line.amount == null ? "" : line.amount,
        line.found || "",
        line.why || "",
        line.where || "",
      ]);
    }
  }

  rows.push([]);
  rows.push(["Total direct cost", "", "", "", "", "", estimate.directCost, "", "", ""]);
  rows.push([
    "Budget range",
    "",
    "",
    "",
    "",
    "",
    `${estimate.range.low} to ${estimate.range.high}`,
    "",
    "",
    "",
  ]);
  if (estimate.excludedValue) {
    rows.push([
      "Excluded by scope",
      "",
      "",
      "",
      "",
      "",
      estimate.excludedValue,
      "Removed from the total above.",
      "",
      "",
    ]);
  }

  rows.push([]);
  rows.push(["Qualifications — what this number assumes", "", "", "", "", "", "", "", "", ""]);
  for (const q of estimate.qualifications) {
    rows.push([
      "Qualification",
      q.title,
      "Assumed",
      q.basisLabel || "",
      "",
      "",
      q.excludedValue == null ? "" : q.excludedValue,
      q.found || "",
      q.why || "",
      q.where || "",
    ]);
  }

  rows.push([]);
  rows.push([
    "Rough order of magnitude for budgeting. Lines marked Assumed were not read from the drawings. Not a bid.",
  ]);

  return [ROM_COLUMNS, ...rows].map((row) => row.map(escape).join(",")).join("\r\n");
}

export function downloadRom(estimate) {
  const blob = new Blob([toRomCsv(estimate)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = romFileName(estimate);
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
