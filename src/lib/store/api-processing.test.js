import { describe, expect, it } from "vitest";
import { mapProcessing, mapScopeStatement } from "./api-mapping.js";

describe("processing mappers", () => {
  it("maps the processing response to camelCase and keeps stage words verbatim", () => {
    const out = mapProcessing({
      documents: [{ id: "d", filename: "E.pdf", doc_type: "Drawings", state: "read", reason: "", sheet_count: 3 }],
      run: { state: "running", reason: "", complete_count: 1, total_count: 3,
             sheets: [{ id: "s", number: "E2.1", title: "Power", stage: "checking", reason: "", note: "", item_count: 4 }] },
    });
    expect(out.documents[0]).toEqual({ id: "d", filename: "E.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 3, sheets: [] });
    expect(out.run.sheets[0]).toEqual({ id: "s", number: "E2.1", title: "Power", stage: "checking", reason: "", note: "", itemCount: 4 });
    expect(out.run.completeCount).toBe(1);
  });
  it("maps each document's sheets, unreadable reason included", () => {
    const out = mapProcessing({
      documents: [{ id: "d", filename: "E.pdf", doc_type: "Drawings", state: "read", reason: "", sheet_count: 2,
                    sheets: [{ id: "s1", number: "E2.1", title: "Power plan", kind: "Electrical plan", unreadable_reason: "" },
                             { id: "s2", number: "E0.1", title: "Schedules", kind: "Schedule", unreadable_reason: "This sheet couldn't be read." }] }],
      run: null,
    });
    expect(out.documents[0].sheets).toEqual([
      { id: "s1", number: "E2.1", title: "Power plan", kind: "Electrical plan", unreadableReason: "" },
      { id: "s2", number: "E0.1", title: "Schedules", kind: "Schedule", unreadableReason: "This sheet couldn't be read." },
    ]);
  });
  it("maps a null run", () => {
    expect(mapProcessing({ documents: [], run: null }).run).toBeNull();
  });
  it("maps a scope statement", () => {
    expect(mapScopeStatement({ id: "x", kind: "by_others", text: "t", edited_text: null, status: "found", document_id: "d", document_filename: "s.pdf", page: 3, quote: "q" }))
      .toEqual({ id: "x", kind: "by_others", text: "t", editedText: null, status: "found", documentId: "d", documentFilename: "s.pdf", page: 3, quote: "q" });
  });
});
