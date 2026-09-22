import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiStore } from "./api.js";
import { mapPlan } from "./api-mapping.js";

const LINE = { key: "spec:d:260519", kind: "spec_section", text: "26 05 19 — Conductors", found_text: "26 05 19 — CONDUCTORS",
  edited_text: "26 05 19 — Conductors", status: "confirmed", document_id: "d", document_filename: "Spec.pdf", page: null,
  quote: "SECTION 26 05 19 CONDUCTORS", division: "26", sheet_number: null, added: false, phase_id: null, places: [] };
const QUESTION = { key: "question:no_specs:project", status: "found", title: "No specification was uploaded", found: "f", why: "w",
  fix: "x", where: "Documents.", document_id: null, document_filename: null, note_id: null };

describe("mapPlan", () => {
  it("maps every section to camelCase, page kept as the 1-based number", () => {
    const out = mapPlan({ read_at: "2026-09-21T10:00:00Z", reading: false, has_drawings: true, undecided: 2,
      scope: [{ id: "x", kind: "excluded", text: "t", edited_text: null, status: "found", document_id: "d", document_filename: "s.pdf", page: 3, quote: "q" }],
      specs: [LINE], schedules: [], phases: [{ ...LINE, key: "phase:PHASE 1", kind: "phase", places: [{ document_id: "d", document_filename: "E.pdf", page: 2, quote: "Phase 1 plan" }] }],
      questions: [QUESTION] });
    expect(out.readAt).toBe("2026-09-21T10:00:00Z");
    expect(out.hasDrawings).toBe(true);
    expect(out.scope[0]).toEqual({ id: "x", kind: "excluded", text: "t", editedText: null, status: "found", documentId: "d", documentFilename: "s.pdf", page: 3, quote: "q" });
    expect(out.specs[0]).toEqual({ key: "spec:d:260519", kind: "spec_section", text: "26 05 19 — Conductors", foundText: "26 05 19 — CONDUCTORS",
      editedText: "26 05 19 — Conductors", status: "confirmed", documentId: "d", documentFilename: "Spec.pdf", page: null,
      quote: "SECTION 26 05 19 CONDUCTORS", division: "26", sheetNumber: null, added: false, phaseId: null, places: [] });
    expect(out.phases[0].places).toEqual([{ documentId: "d", documentFilename: "E.pdf", page: 2, quote: "Phase 1 plan" }]);
    expect(out.questions[0]).toEqual({ key: "question:no_specs:project", status: "found", title: "No specification was uploaded", found: "f",
      why: "w", fix: "x", where: "Documents.", documentId: null, documentFilename: null, noteId: null });
  });
});

describe("plan store methods", () => {
  let store;
  let calls;
  beforeEach(() => {
    calls = [];
    vi.stubGlobal("fetch", vi.fn(async (path, init) => {
      calls.push([path, init]);
      const body = path.endsWith("/plan") ? { read_at: null, reading: false, has_drawings: false, undecided: 0, scope: [], specs: [], schedules: [], phases: [], questions: [] }
        : init.method === "DELETE" ? null : path.includes("/questions/") ? QUESTION : LINE;
      return { ok: true, status: body === null ? 204 : 200, text: async () => (body === null ? "" : JSON.stringify(body)) };
    }));
    store = createApiStore();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("getPlan fetches and maps", async () => {
    const plan = await store.getPlan("p1");
    expect(calls[0][0]).toBe("/api/projects/p1/plan");
    expect(plan.undecided).toBe(0);
  });

  it("decidePlanLine sends exactly one of status or edited_text and encodes the key", async () => {
    await store.decidePlanLine("p1", "phase:PHASE 1", { status: "confirmed" });
    expect(calls[0][0]).toBe("/api/projects/p1/plan/lines/phase%3APHASE%201");
    expect(JSON.parse(calls[0][1].body)).toEqual({ status: "confirmed" });
    await store.decidePlanLine("p1", "spec:d:260519", { editedText: "x" });
    expect(JSON.parse(calls[1][1].body)).toEqual({ edited_text: "x" });
  });

  it("answerPlanQuestion posts the body and maps a question", async () => {
    const out = await store.answerPlanQuestion("p1", "question:no_specs:project", "Drawings are the whole set.");
    expect(calls[0][0]).toBe("/api/projects/p1/plan/questions/question%3Ano_specs%3Aproject/answer");
    expect(JSON.parse(calls[0][1].body)).toEqual({ body: "Drawings are the whole set." });
    expect(out.title).toBe("No specification was uploaded");
  });

  it("addPlanPhase and removePlanPhase", async () => {
    await store.addPlanPhase("p1", "Phase 2");
    expect(calls[0][0]).toBe("/api/projects/p1/plan/phases");
    expect(JSON.parse(calls[0][1].body)).toEqual({ name: "Phase 2" });
    expect(await store.removePlanPhase("p1", "ph1")).toBeNull();
    expect(calls[1][0]).toBe("/api/projects/p1/plan/phases/ph1");
    expect(calls[1][1].method).toBe("DELETE");
  });
});
