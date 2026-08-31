/* Type detection from real construction bid-set filenames. The point is
   that a whole set's filenames sort themselves without the estimator
   touching a dropdown, so the cases are the actual names from a real
   Division 26 bid set. */

import { describe, expect, it } from "vitest";
import { detectDocType } from "./detectDocType.js";

describe("detectDocType", () => {
  it.each([
    ["21_1001_unalaska_library_cd_biddrawings.pdf", "Drawings"],
    ["part_1_of_4_unak_library_as-built_drawings.pdf", "Drawings"],
    ["unak_library_detail_book.pdf", "Drawings"],
    ["specs_part_1.pdf", "Specifications"],
    ["15105_library_project_manual_for_bid_10-1-21.pdf", "Specifications"],
    ["library_expansion_rebid_addendum_01.pdf", "Addendum"],
    ["unalaska_library_improvements_geotechnical_report_final.pdf", "Other"],
    ["unak_library-struct-ironworks_shops.pdf", "Other"],
    ["unak_library_-_fp_system_amc_comments.pdf", "Other"],
    ["111621_record_of_bid_document.pdf", "Other"],
    ["library_addn_bid_tab_11-18-21_v1.pdf", "Other"],
  ])("classifies %s as %s", (filename, expected) => {
    expect(detectDocType(filename)).toBe(expected);
  });

  it("defaults an unrecognized name to Drawings", () => {
    expect(detectDocType("E100.pdf")).toBe("Drawings");
    expect(detectDocType("")).toBe("Drawings");
  });

  it("prefers Addendum even when the name also mentions drawings", () => {
    expect(detectDocType("addendum_02_revised_drawings.pdf")).toBe("Addendum");
  });
});
