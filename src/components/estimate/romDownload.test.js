import { describe, expect, it } from "vitest";
import { ROM_COLUMNS, romFileName, toRomCsv } from "./romDownload.js";

function line(extra = {}) {
  return {
    title: "Power",
    origin: "counted",
    basisLabel: null,
    value: "2",
    unit: "lines",
    amount: 450,
    found: "2 counted lines.",
    why: null,
    where: "Takeoff spreadsheet",
    ...extra,
  };
}

function estimate(extra = {}) {
  return {
    projectName: "Kittle's Saxony",
    directCost: 486200,
    range: { low: 413000, high: 559000 },
    excludedValue: 0,
    sections: [{ key: "takeoff", label: "Takeoff quantities", lines: [line()] }],
    qualifications: [],
    ...extra,
  };
}

function rows(csv) {
  return csv.split("\r\n");
}

describe("toRomCsv", () => {
  it("leads with the column header the screen's own columns mirror", () => {
    expect(rows(toRomCsv(estimate()))[0]).toBe(ROM_COLUMNS.join(","));
  });

  it("marks an assumed line as assumed and names its basis", () => {
    const csv = toRomCsv(
      estimate({
        sections: [
          {
            key: "takeoff",
            label: "Takeoff quantities",
            lines: [
              line({
                title: "Branch conduit and wire",
                origin: "assumed",
                basisLabel: "Rule of thumb",
                amount: null,
              }),
            ],
          },
        ],
      }),
    );
    const row = rows(csv).find((r) => r.includes("Branch conduit and wire"));
    expect(row).toContain("Assumed");
    expect(row).toContain("Rule of thumb");
  });

  it("leaves the amount blank rather than zero for a line nothing priced", () => {
    /* A zero reads as a decision somebody made. Nothing priced it. */
    const csv = toRomCsv(
      estimate({
        sections: [
          { key: "takeoff", label: "Takeoff quantities", lines: [line({ amount: null })] },
        ],
      }),
    );
    expect(rows(csv)[1].split(",")[6]).toBe("");
  });

  it("carries the total, the range and the not-a-bid statement", () => {
    const csv = toRomCsv(estimate());
    expect(csv).toContain("Total direct cost");
    expect(csv).toContain("413000 to 559000");
    expect(csv).toContain("Not a bid.");
  });

  it("states excluded value only when scope removed something", () => {
    expect(toRomCsv(estimate())).not.toContain("Excluded by scope");
    expect(toRomCsv(estimate({ excludedValue: 12400 }))).toContain("Excluded by scope");
  });

  it("writes every qualification into the file", () => {
    /* A download that dropped the disclosures would be the bare number
       this whole feature exists to prevent handing over. */
    const csv = toRomCsv(
      estimate({
        qualifications: [
          {
            title: "Temporary power excluded",
            basisLabel: "Standard exclusion",
            found: "No document addressed temporary power.",
            why: "It is commonly the general contractor's.",
            where: "Scope documents",
            excludedValue: null,
          },
        ],
      }),
    );
    expect(csv).toContain("Temporary power excluded");
    expect(csv).toContain("No document addressed temporary power.");
  });

  it("quotes a field containing a comma rather than splitting the row", () => {
    const csv = toRomCsv(
      estimate({
        sections: [
          {
            key: "takeoff",
            label: "Takeoff quantities",
            lines: [line({ found: "Two scale labels, neither confirmed." })],
          },
        ],
      }),
    );
    expect(rows(csv)).toHaveLength(rows(toRomCsv(estimate())).length);
    expect(csv).toContain('"Two scale labels, neither confirmed."');
  });

  it("doubles an embedded quote", () => {
    const csv = toRomCsv(
      estimate({
        sections: [
          {
            key: "takeoff",
            label: "Takeoff quantities",
            lines: [line({ found: 'Sheet says 1/8" = 1\'-0".' })],
          },
        ],
      }),
    );
    expect(csv).toContain('"Sheet says 1/8"" = 1\'-0""."');
  });

  it("defuses a formula a drawing set could carry into a cell", () => {
    /* Extracted document text is untrusted input. The reasoning that
       keeps it out of the prompt as instruction keeps it out of a
       spreadsheet as a formula. */
    for (const hostile of ['=HYPERLINK("http://x","click")', "+1+1", "-1+1", "@SUM(A1)"]) {
      const csv = toRomCsv(
        estimate({
          sections: [
            {
              key: "takeoff",
              label: "Takeoff quantities",
              lines: [line({ title: hostile })],
            },
          ],
        }),
      );
      // The trigger character is never the first thing in the cell: an
      // apostrophe sits in front of it, whether or not the cell also
      // needed quoting for its commas.
      expect(csv).toMatch(new RegExp(`,"?'\\${hostile[0]}`));
      expect(csv).not.toMatch(new RegExp(`,"?\\${hostile[0]}`));
    }
  });

  it("leaves an ordinary negative amount alone", () => {
    /* The guard is on text fields reaching a cell, not on arithmetic the
       product itself produced. */
    expect(toRomCsv(estimate({ directCost: 486200 }))).toContain("486200");
  });
});

describe("the unfinished-estimate warning", () => {
  it("leads the file when the document is not ready to hand over", () => {
    /* Second Codex review, finding 7. The screen shows this warning and
       the download dropped it, so the one artifact that actually leaves
       the building was the only place it did not appear. */
    const csv = toRomCsv(
      estimate({ pendingReason: "The disclosures for this estimate have not been generated yet." }),
    );
    expect(rows(csv)[0]).toContain("Not ready to hand over");
    expect(rows(csv)[0]).toContain("have not been generated yet");
  });

  it("carries the pricing basis, so the emailed file says what priced it", () => {
    /* Same rule as the pending reason above: the screen states what
       priced the job, and the file a GC opens is the one artifact that
       leaves the building. A short total whose cause stayed behind in
       the browser is a number with no basis attached. */
    const csv = toRomCsv(
      estimate({ pricingNote: "Automated pricing wasn't available, so regional cost data was used." }),
    );
    expect(csv).toContain("Pricing basis");
    expect(csv).toContain("Automated pricing wasn't available");
  });

  it("omits the pricing basis line when the project has no note", () => {
    expect(toRomCsv(estimate())).not.toContain("Pricing basis");
  });

  it("puts it above the column header, not inside the table", () => {
    const csv = toRomCsv(estimate({ pendingReason: "Not generated yet." }));
    const header = rows(csv).indexOf(ROM_COLUMNS.join(","));
    expect(header).toBeGreaterThan(0);
    expect(rows(csv)[0].startsWith("Not ready")).toBe(true);
  });

  it("says nothing when the document is finished", () => {
    expect(toRomCsv(estimate())).not.toContain("Not ready to hand over");
  });
});

describe("romFileName", () => {
  it("names the project and says what the file is", () => {
    expect(romFileName({ projectName: "Kittle's Saxony" })).toBe(
      "kittle-s-saxony-rom-estimate.csv",
    );
  });

  it("falls back rather than producing a nameless file", () => {
    expect(romFileName({ projectName: "   " })).toBe("estimate-rom-estimate.csv");
    expect(romFileName(undefined)).toBe("estimate-rom-estimate.csv");
  });
});
