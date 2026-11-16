/* The ROM's origin tags must not wear a review label's colour.

   This reads styles.css rather than a rendered component, because the
   thing under test is a token choice and the failure mode is somebody
   reaching for `--amber` while writing a new estimate style. A render
   test would pass with the wrong hue; this one names the rule.

   docs/specs/rom-estimate.md, anti-goals: "A fifth status label.
   `counted` and `assumed` describe where a NUMBER came from. They are a
   different axis from the four review labels ... and they must not be
   rendered with the review-status components or colours." Amber is
   `.pill--attention`'s hue — an amber tag reading ASSUMED beside an
   amber pill reading Needs attention is how the four labels become
   five. Plum is the pair the product already reserves for a second
   vocabulary, on note status. */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// Resolved from the project root rather than import.meta.url: the test
// environment serves this module over a non-file scheme, so new URL()
// has nothing to resolve against.
const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

/** Every declaration block whose selector mentions one of these. */
function blocksFor(fragment) {
  const out = [];
  const re = /([^{}]+)\{([^}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    if (m[1].includes(fragment)) out.push({ selector: m[1].trim(), body: m[2] });
  }
  return out;
}

describe("the counted/assumed axis keeps its own colours", () => {
  it("has rules to check", () => {
    /* So a renamed class silently empties the assertions below rather
       than passing them. */
    expect(blocksFor(".est-tag-assumed").length).toBeGreaterThan(0);
    expect(blocksFor(".est-tag-counted").length).toBeGreaterThan(0);
  });

  it("never paints an origin tag in a review-status hue", () => {
    for (const fragment of [".est-tag-assumed", ".est-tag-counted"]) {
      for (const block of blocksFor(fragment)) {
        for (const reviewHue of ["--amber", "--blue", "--red", "--green"]) {
          expect(block.body).not.toContain(reviewHue);
        }
      }
    }
  });

  it("paints assumed plum and counted slate", () => {
    const assumed = blocksFor(".est-tag-assumed").map((b) => b.body).join(" ");
    const counted = blocksFor(".est-tag-counted").map((b) => b.body).join(" ");
    expect(assumed).toContain("--plum");
    expect(counted).toContain("--slate");
  });

  it("keeps the assumed row's dashed edge off the review hues too", () => {
    /* The dashed edge is the third channel carrying the same fact, so
       it has to follow the same rule as the tag. */
    const rows = blocksFor(".est-assumed .est-first");
    expect(rows.length).toBeGreaterThan(0);
    for (const block of rows) {
      expect(block.body).not.toContain("--amber");
      expect(block.body).toContain("--plum");
    }
  });

  it("matches note status, the other second vocabulary, in using plum", () => {
    /* Not a coincidence to be refactored away: the two screens are
       solving the same problem and should look like it. */
    const note = blocksFor(".note-status--open").map((b) => b.body).join(" ");
    expect(note).toContain("--plum");
  });

  it("leaves Needs attention its own amber", () => {
    /* The inverse guard. If a future change moved the review pill off
       amber, the separation above would still hold but this test
       records which vocabulary owns the hue. */
    const pill = blocksFor(".pill--attention").map((b) => b.body).join(" ");
    expect(pill).toContain("--amber");
  });
});

describe("the confidence meter keeps off the review hues too", () => {
  it("has rules to check", () => {
    expect(blocksFor(".conf-step").length).toBeGreaterThan(0);
  });

  it("never paints a step in a review-status hue", () => {
    /* A meter that turned amber at 4 would read as *Needs attention*,
       and a red-to-green ramp would put green on something no person
       has approved — green is reserved for estimator-approved content
       and nothing else. */
    for (const fragment of [".conf-bar", ".conf-step"]) {
      for (const block of blocksFor(fragment)) {
        for (const reviewHue of ["--amber", "--red", "--green"]) {
          expect(block.body).not.toContain(reviewHue);
        }
      }
    }
  });

  it("uses the second-vocabulary slate, like the counted tag", () => {
    const steps = blocksFor(".conf-step").map((b) => b.body).join(" ");
    expect(steps).toContain("--slate");
  });
});
