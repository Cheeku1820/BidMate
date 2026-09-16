// src/lib/store/api-conversation.test.js
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiStore } from "./api.js";

const sse = (...blocks) =>
  new Response(
    new ReadableStream({
      start(controller) {
        const enc = new TextEncoder();
        for (const b of blocks) controller.enqueue(enc.encode(b));
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );

describe("conversation calls", () => {
  let fetchMock;
  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("lists the thread with camelCase timestamps", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ messages: [
      { id: "m1", role: "estimator", text: "q", screen: { name: "export" }, created_at: "2026-09-16T10:00:00Z" },
    ] }), { status: 200 }));
    const rows = await createApiStore().listConversation("p1");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/projects/p1/conversation");
    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
    expect(rows).toEqual([{ id: "m1", role: "estimator", text: "q", screen: { name: "export" }, createdAt: "2026-09-16T10:00:00Z" }]);
  });

  it("streams deltas, even split across chunks, then resolves with done", async () => {
    fetchMock.mockResolvedValue(sse(
      'event: delta\ndata: {"text":"Noth',
      'ing"}\n\nevent: delta\ndata: {"text":" blocks."}\n\nevent: done\ndata: {"id":"a1"}\n\n',
    ));
    const deltas = [];
    const result = await createApiStore().sendMessage("p1", { text: "q", screen: { name: "export" } }, (t) => deltas.push(t));
    expect(deltas).toEqual(["Nothing", " blocks."]);
    expect(result).toEqual({ id: "a1" });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ text: "q", screen: { name: "export" } });
  });

  it("rejects with the error event's code and message", async () => {
    fetchMock.mockResolvedValue(sse('event: delta\ndata: {"text":"Partial"}\n\nevent: error\ndata: {"code":"interrupted","message":"Answer interrupted — ask again"}\n\n'));
    await expect(createApiStore().sendMessage("p1", { text: "q", screen: { name: "export" } }, () => {}))
      .rejects.toEqual({ code: "interrupted", message: "Answer interrupted — ask again" });
  });

  it("rejects with the 503 body when the server has no key", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: { code: "not_configured", message: "The conversation panel isn't set up on this server" } }), { status: 503 }));
    await expect(createApiStore().sendMessage("p1", { text: "q", screen: { name: "export" } }, () => {}))
      .rejects.toEqual({ code: "not_configured", message: "The conversation panel isn't set up on this server" });
  });

  it("passes the abort signal through", async () => {
    fetchMock.mockResolvedValue(sse('event: done\ndata: {"id":"a1"}\n\n'));
    const controller = new AbortController();
    await createApiStore().sendMessage("p1", { text: "q", screen: { name: "export" } }, () => {}, controller.signal);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });
});
