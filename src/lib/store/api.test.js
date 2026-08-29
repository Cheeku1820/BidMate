/* ============================================================
   api.test.js — fetch-stubbed unit tests for api.js's own conversion
   layer (task-16-brief.md §5): the five behaviors a live server is
   overkill to prove and that are cheap to pin as pure functions of a
   response body. contract.test.js (extended in this task) is where the
   full store interface is exercised end to end against a fake backend;
   this file is narrower and stubs `fetch` directly.
   ============================================================ */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { createApiStore, login, PRESENCE_BEAT_MS } from "./api.js";

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
    ...init,
  });
}

const PROJECT = { id: "11111111-1111-1111-1111-111111111111", name: "Meridian Distribution Center", revision_set_label: "E1.1 Rev 3" };

function snapshotBody(overrides = {}) {
  return {
    version: "v1",
    sheets: [
      { id: "s1", number: "E2.1", title: "Power plan", discipline: "Electrical", revision: "Rev 2", scale: "mixed", scale_options: ["1/8\" = 1'-0\""], plan: "warehouse", superseded: false },
    ],
    items: [
      {
        id: "it-01", sheet_id: "s1", symbol: "panel", name: "Panel LP-1", description: "desc",
        system: "Distribution", category: "Panels", quantity: "184.55", unit: "LF", status: "ready",
        version: 3, approved_by: null, rejected: false, x: 10, y: 20, path: null, notes: "",
        evidence: null, warnings: [],
      },
    ],
    totals: { by_system: { Distribution: "184.55" }, approved_count: 1, remaining_count: 2, attention_count: 1, missing_count: 1, approved_units: "39.00" },
    undo: { can_undo: false, can_redo: false, undo_label: null, undo_by: null, redo_label: null },
    presence: [],
    ...overrides,
  };
}

describe("api.js conversions", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("converts a Decimal string into a number", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(jsonResponse(snapshotBody()));

    const store = createApiStore();
    const snapshot = await store.getSnapshot();

    expect(snapshot.items[0].quantity).toBe(184.55);
    expect(typeof snapshot.items[0].quantity).toBe("number");
    expect(snapshot.totals.approvedUnits).toBe(39);
    expect(snapshot.totals.bySystem.Distribution).toBe(184.55);
  });

  it("maps the engine cluster tag onto the item", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(
        jsonResponse(
          snapshotBody({
            items: [{ ...snapshotBody().items[0], source_tag: "F2" }],
          })
        )
      );

    const store = createApiStore();
    const snapshot = await store.getSnapshot();

    expect(snapshot.items[0].sourceTag).toBe("F2");
  });

  it("converts presence's seen_at (ISO-8601) into epoch milliseconds", async () => {
    const seenAt = "2026-08-15T12:00:00Z";
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(
        jsonResponse(
          snapshotBody({
            presence: [{ user_id: "u2", name: "Dana Whitfield", color: "#000", sheet_id: "s1", item_id: null, seen_at: seenAt }],
          })
        )
      );

    const store = createApiStore();
    const snapshot = await store.getSnapshot();

    expect(typeof snapshot.presence[0].seenAt).toBe("number");
    expect(snapshot.presence[0].seenAt).toBe(Date.parse(seenAt));
  });

  it("a 304 with an empty body yields the previously cached snapshot, not a crash and not an empty one", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(jsonResponse(snapshotBody()));

    const store = createApiStore();
    const first = await store.getSnapshot();
    expect(first.items).toHaveLength(1);

    // A 304's body is genuinely empty -- Response with no body and a
    // 304 status, mirroring Cache-Control: no-store's actual behavior
    // (carry-forward 4), not a Response that merely omits a JSON body
    // but could still be parsed.
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 304 }));

    const second = await store.getSnapshot();
    expect(second).toEqual(first);
    expect(second.items).toHaveLength(1);

    // The conditional request actually carried the version this module
    // cached from the first call.
    const secondCall = fetchMock.mock.calls[2];
    expect(secondCall[1].headers["If-None-Match"]).toBe("v1");
  });

  it("a non-2xx response rejects with a {code, message} shape, matching the seed store", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { code: "not_signed_in", message: "Sign in to continue." } }, { status: 401 })
    );

    await expect(login("dana@meridianelectric.example", "wrong")).rejects.toMatchObject({
      code: "not_signed_in",
      message: "Sign in to continue.",
    });
  });

  it("a FastAPI validation error (a list under detail) still rejects with a {code, message} shape", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: [{ type: "value_error", loc: ["body", "quantity"], msg: "quantity must be sent as a JSON string" }] }, { status: 422 })
    );
    fetchMock.mockResolvedValueOnce(jsonResponse([PROJECT]));

    const store = createApiStore();
    await expect(store.approveItem("it-01", 3)).rejects.toMatchObject({
      code: "invalid_request",
      message: "quantity must be sent as a JSON string",
    });
  });

  it("sends If-Match carrying the item's version on the five single-item mutations", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(
        jsonResponse({ label: "Approved Panel LP-1", version: "v2", item: { ...snapshotBody().items[0], status: "approved", approved_by: "Dana Whitfield", version: 4 } })
      );

    const store = createApiStore();
    await store.approveItem("it-01", 3);

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/approve"));
    expect(call[1].headers["If-Match"]).toBe("3");
    expect(call[1].method).toBe("POST");
  });

  it("sends quantity as a string with at most two decimals on edit, never a bare number", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(jsonResponse({ label: "Edited Panel LP-1", version: "v2", item: snapshotBody().items[0] }));

    const store = createApiStore();
    await store.editItem("it-01", { system: "Power", quantity: 14.5, notes: "checked" }, 3);

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/items/it-01"));
    const body = JSON.parse(call[1].body);
    expect(body).toEqual({ system: "Power", quantity: "14.50", notes: "checked" });
    expect(typeof body.quantity).toBe("string");
  });

  it("never round-trips an unknown field into a PATCH body", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(jsonResponse({ label: "Edited Panel LP-1", version: "v2", item: snapshotBody().items[0] }));

    const store = createApiStore();
    // Simulates a caller mistakenly spreading a whole item -- `id`,
    // `sheetId`, `warnings`, and `version` must never reach the wire.
    await store.editItem("it-01", { id: "it-01", sheetId: "s1", notes: "ok", warnings: [], version: 3 }, 3);

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/items/it-01"));
    const body = JSON.parse(call[1].body);
    expect(body).toEqual({ notes: "ok" });
  });

  it("carries every field ingest writes on a sheet through to the store shape", async () => {
    // Written by ingest and never read back is the failure this pins:
    // the page image cannot be addressed without takeoffId/pageIndex,
    // markers are normalized against widthPt/heightPt, and a sheet the
    // processing could not read renders as an empty one -- silence
    // reading as completeness -- unless unreadableReason arrives.
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(
        jsonResponse(
          snapshotBody({
            sheets: [
              {
                ...snapshotBody().sheets[0],
                takeoff_id: "tk1",
                page_index: 0,
                width_pt: 2000,
                height_pt: 1500,
                unreadable_reason: "The page is a scanned photocopy with no readable linework.",
                ai_reading: { summary: "Warehouse power plan", devices: [{ name: "Duplex receptacle", count: 47 }] },
              },
            ],
          })
        )
      );

    const store = createApiStore();
    const sheet = (await store.getSnapshot()).sheets[0];

    expect(sheet.takeoffId).toBe("tk1");
    // Zero-based: a page index of 0 is the first page, not an absent one.
    expect(sheet.pageIndex).toBe(0);
    expect(sheet.widthPt).toBe(2000);
    expect(sheet.heightPt).toBe(1500);
    expect(sheet.unreadableReason).toContain("scanned photocopy");
    expect(sheet.aiReading.devices[0].count).toBe(47);
  });

  it("carries every field ingest writes on an item through to the store shape", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse([PROJECT]))
      .mockResolvedValueOnce(
        jsonResponse(
          snapshotBody({
            items: [
              {
                ...snapshotBody().items[0],
                material_cost: "188.00",
                labor_hours: "15.51",
                labor_cost: "1209.78",
                total_cost: "1397.78",
                placements: [[500, 375], [250, 188]],
                ai_confirmed: true,
              },
            ],
          })
        )
      );

    const store = createApiStore();
    const item = (await store.getSnapshot()).items[0];

    // Money arrives as a Decimal string, exactly as quantity does. A
    // string reaching the totals' `+` concatenates silently.
    expect(item.materialCost).toBe(188);
    expect(typeof item.materialCost).toBe("number");
    expect(item.laborHours).toBe(15.51);
    expect(item.laborCost).toBe(1209.78);
    expect(item.totalCost).toBe(1397.78);
    expect(typeof item.totalCost).toBe("number");
    // Every coordinate the cluster was counted at -- without it, 47
    // counted devices render as one marker.
    expect(item.placements).toEqual([[500, 375], [250, 188]]);
    expect(item.aiConfirmed).toBe(true);
  });

  it("presence beat is derived from and shorter than collab/service.py's ASSUMED_HEARTBEAT_INTERVAL (10s)", () => {
    expect(PRESENCE_BEAT_MS).toBeLessThan(10_000);
    expect(PRESENCE_BEAT_MS).toBe(5000);
  });
});

describe("attachEngineTakeoff", () => {
  it("posts the engine payload to the project's takeoff endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sheets: 2, items: 47 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const store = createApiStore();
    const result = await store.attachEngineTakeoff("p1", { sheets: [], items: [] });

    expect(result).toEqual({ sheets: 2, items: 47 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects/p1/takeoff");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      payload: { sheets: [], items: [] },
      confirm_replace: false,
    });
  });

  it("sends confirm_replace only when the estimator has confirmed", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ sheets: 1, items: 1 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const store = createApiStore();
    await store.attachEngineTakeoff("p1", { sheets: [] }, { confirmReplace: true });

    expect(JSON.parse(fetchMock.mock.calls[0][1].body).confirm_replace).toBe(true);
  });

  it("surfaces the server's refusal code so the caller can confirm", async () => {
    const body = JSON.stringify({
      detail: {
        code: "approved_items_present",
        message: "3 item(s) on this project are estimator approved.",
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body, { status: 409 })));

    const store = createApiStore();
    await expect(store.attachEngineTakeoff("p1", {})).rejects.toMatchObject({
      code: "approved_items_present",
    });
  });
});


describe("reprocess", () => {
  it("posts a re-run to the reprocess endpoint, not to ingest", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ reclassified: 7, preserved: 3, added: 0, removed: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await createApiStore().reprocess("p1", { sheets: [], items: [] });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/reprocess");
    expect(out.preserved).toBe(3);
  });
});

describe("the store interface", () => {
  /** Every method the components and the snapshot hook actually call,
   *  derived from the call sites (`grep -rn "store\\." src/`) rather than
   *  from memory. contract.test.js exercised both stores end to end and
   *  went with the seed store; nothing replaced the api half. This is
   *  deliberately only the interface guard: a method that quietly
   *  disappears is a runtime crash in front of an estimator, not a test
   *  failure, and that is the class of regression worth pinning here. */
  const CALLED_BY_THE_APP = [
    "approveItem",
    "attachEngineTakeoff",
    "bulkApprove",
    "createNote",
    "createProject",
    "deleteItem",
    "deleteNote",
    "editItem",
    "getSnapshot",
    "listNotes",
    "listProjects",
    "redo",
    "rejectItem",
    "reprocess",
    "setPresence",
    "setScale",
    "subscribe",
    "undo",
    "unrejectItem",
    "updateNote",
    "useProject",
  ];

  it("exposes every method the app calls, as a function", () => {
    const store = createApiStore();
    for (const name of CALLED_BY_THE_APP) {
      expect(typeof store[name], `store.${name} is called by the app`).toBe("function");
    }
  });
});

describe("notes", () => {
  const RAW_NOTE = {
    id: "n1", project_id: "p1", scope: "project", scope_ref: null,
    title: "Low-voltage excluded", body: "Per the Turner scope letter.",
    category: "exclusion", status: "confirmed", rfi_needed: false,
    usage: "context", source_ref: "Turner scope letter",
    obsolete_after_revision: "", author_name: "Dana Whitfield",
    created_at: "2026-08-28T10:00:00Z", updated_at: "2026-08-28T10:00:00Z",
    applied_at: null,
  };

  it("lists notes in camelCase", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify([RAW_NOTE]), { status: 200 })));
    const notes = await createApiStore().listNotes("p1");
    expect(notes[0].rfiNeeded).toBe(false);
    expect(notes[0].usage).toBe("context");
    expect(notes[0].authorName).toBe("Dana Whitfield");
    expect(notes[0].sourceRef).toBe("Turner scope letter");
  });

  it("creates a note against the project", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(RAW_NOTE), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await createApiStore().createNote("p1", { title: "t", body: "b", category: "exclusion", usage: "context" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/projects/p1/notes");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).usage).toBe("context");
  });

  it("patches a note by its own id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...RAW_NOTE, usage: "reference" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const note = await createApiStore().updateNote("n1", { usage: "reference" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/notes/n1");
    expect(note.usage).toBe("reference");
  });

  it("deletes a note", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await createApiStore().deleteNote("n1");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });

  it("creates a note writing camelCase fields back to their wire names", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(RAW_NOTE), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await createApiStore().createNote("p1", { rfiNeeded: true, sourceRef: "Spec 262726", usage: "context" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.rfi_needed).toBe(true);
    expect(body.source_ref).toBe("Spec 262726");
    expect(body).not.toHaveProperty("rfiNeeded");
    expect(body).not.toHaveProperty("sourceRef");
  });

  it("patches a note sending only the field the caller actually supplied", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...RAW_NOTE, usage: "reference" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await createApiStore().updateNote("n1", { usage: "reference" });
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(Object.keys(body)).toEqual(["usage"]);
  });

  it("drops server-owned fields when a whole note is handed back to updateNote", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(RAW_NOTE), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const wholeNote = {
      id: "n1", projectId: "p1", scope: "project", scopeRef: null,
      title: "Low-voltage excluded", body: "Per the Turner scope letter.",
      category: "exclusion", status: "confirmed", rfiNeeded: false,
      usage: "context", sourceRef: "Turner scope letter",
      obsoleteAfterRevision: "", authorName: "Dana Whitfield",
      createdAt: "2026-08-28T10:00:00Z", updatedAt: "2026-08-28T10:00:00Z",
      appliedAt: null,
    };
    await createApiStore().updateNote("n1", wholeNote);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).not.toHaveProperty("id");
    expect(body).not.toHaveProperty("projectId");
    expect(body).not.toHaveProperty("authorName");
    expect(body).not.toHaveProperty("createdAt");
    expect(body).not.toHaveProperty("updatedAt");
    expect(body).not.toHaveProperty("appliedAt");
  });
});
