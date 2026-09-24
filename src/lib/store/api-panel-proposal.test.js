import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiStore } from "./api.js";
import { mapPanelProposal } from "./api-mapping.js";

const ITEM = {
  kind: "item", summary: "Name 6 items on E2.1 2x4 LED troffer, type F.", note: "Approving stays with you.",
  count: 6, sheet_number: "E2.1", item_id: "i1", approve: false,
  proposal: { intent: "reclassify", target_item_ids: ["i1", "i2"], versions: { i1: 1, i2: 1 }, name: "2x4 LED troffer, type F" },
  targets_preview: [{ label: "Unclassified symbol", detail: "6 EA" }], more_count: 2,
};

describe("mapPanelProposal", () => {
  it("camelCases the card's own fields and leaves the apply payload alone", () => {
    const out = mapPanelProposal(ITEM);
    expect(out.kind).toBe("item");
    expect(out.sheetNumber).toBe("E2.1");
    expect(out.itemId).toBe("i1");
    expect(out.moreCount).toBe(2);
    expect(out.targetsPreview).toEqual([{ label: "Unclassified symbol", detail: "6 EA" }]);
    // Posted back verbatim to apply-proposal, so it must not be rewritten.
    expect(out.proposal).toEqual(ITEM.proposal);
  });

  it("maps a scope arm and a null", () => {
    const scope = mapPanelProposal({ kind: "scope", summary: "Confirm…", statement_id: "s1", status: "confirmed",
                                     current_text: "Site lighting.", quote: "- Site lighting.", targets_preview: [], more_count: 0 });
    expect(scope.statementId).toBe("s1");
    expect(scope.currentText).toBe("Site lighting.");
    expect(mapPanelProposal(null)).toBeNull();
  });
});

describe("the proposal event and the status call", () => {
  let store;
  let calls;

  function sse(...blocks) {
    const body = blocks.join("");
    return {
      ok: true, status: 200,
      body: { getReader: () => {
        let sent = false;
        return { read: async () => (sent ? { done: true } : ((sent = true), { value: new TextEncoder().encode(body), done: false })) };
      } },
    };
  }

  beforeEach(() => {
    calls = [];
    store = createApiStore();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("returns the mapped proposal with the done payload", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse(
      'event: delta\ndata: {"text":"Six items."}\n\n',
      `event: proposal\ndata: ${JSON.stringify({ id: "m1", proposal: ITEM })}\n\n`,
      'event: done\ndata: {"id":"m1"}\n\n',
    )));
    const deltas = [];
    const out = await store.sendMessage("p1", { text: "these are type F", screen: { name: "takeoff" } }, (t) => deltas.push(t));
    expect(deltas).toEqual(["Six items."]);
    expect(out.id).toBe("m1");
    expect(out.proposal.sheetNumber).toBe("E2.1");
  });

  it("returns a null proposal when no event arrived", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sse('event: delta\ndata: {"text":"Fourteen sheets."}\n\n',
                                                 'event: done\ndata: {"id":"m2"}\n\n')));
    const out = await store.sendMessage("p1", { text: "how many sheets?", screen: { name: "takeoff" } }, () => {});
    expect(out.proposal).toBeNull();
  });

  it("setProposalStatus patches the message", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path, init) => {
      calls.push([path, init]);
      return { ok: true, status: 200, text: async () => JSON.stringify({ id: "m1", role: "answer", text: "…", proposal: ITEM, proposal_status: "applied" }) };
    }));
    const out = await store.setProposalStatus("p1", "m1", "applied");
    expect(calls[0][0]).toBe("/api/projects/p1/conversation/messages/m1/proposal");
    expect(JSON.parse(calls[0][1].body)).toEqual({ status: "applied" });
    expect(out.proposalStatus).toBe("applied");
  });
});
