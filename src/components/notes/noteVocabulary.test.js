import { describe, expect, it } from "vitest";
import { calculationEffect, CATEGORY_LABELS, SCOPE_LABELS } from "./noteVocabulary.js";

describe("calculationEffect", () => {
  it("says a context note is used in this estimate", () => {
    expect(calculationEffect({ usage: "context", scope: "project" }).label).toBe("Used in this estimate");
  });

  it("says a reference note is reference only", () => {
    expect(calculationEffect({ usage: "reference", scope: "project" }).label).toBe("Reference only");
  });

  it("says a company-scoped note is a company standard", () => {
    expect(calculationEffect({ usage: "context", scope: "company" }).label).toBe("Company standard");
  });

  it("labels every scope and category it accepts", () => {
    for (const s of ["company", "project", "sheet", "item"]) expect(SCOPE_LABELS[s]).toBeTruthy();
    for (const c of ["existing_condition", "exclusion", "customer_instruction",
                     "labor_consideration", "company_rule"]) expect(CATEGORY_LABELS[c]).toBeTruthy();
  });
});
