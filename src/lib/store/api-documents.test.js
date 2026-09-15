import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { createApiStore } from "./api.js";
import { mapDocument } from "./api-mapping.js";

const raw = { id: "d1", project_id: "p1", filename: "E-set.pdf", doc_type: "Drawings", size_bytes: 10, sha256: "ab", status: "uploaded", error: "", created_at: "2026-09-15T00:00:00Z" };

describe("mapDocument", () => {
  test("renames to camelCase and keeps the closed-set values", () => {
    expect(mapDocument(raw)).toEqual({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 10, sha256: "ab", status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z" });
  });
});

/** A stand-in XMLHttpRequest that records what was sent and lets a test
 *  fire progress and completion by hand. */
class FakeXHR {
  static last = null;
  constructor() { this.upload = {}; this.status = 0; this.responseText = ""; FakeXHR.last = this; }
  open(method, url) { this.method = method; this.url = url; }
  send(form) { this.form = form; }
  setRequestHeader() {}
}

describe("uploadDocument", () => {
  let store;
  beforeEach(() => { vi.stubGlobal("XMLHttpRequest", FakeXHR); store = createApiStore(); });
  afterEach(() => vi.unstubAllGlobals());

  test("posts multipart with credentials, reports progress, resolves the mapped document", async () => {
    const onProgress = vi.fn();
    const p = store.uploadDocument("p1", new File([new Uint8Array(4)], "E-set.pdf", { type: "application/pdf" }), "Drawings", { onProgress });
    const xhr = FakeXHR.last;
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/projects/p1/documents");
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.form.get("doc_type")).toBe("Drawings");
    expect(xhr.form.get("file").name).toBe("E-set.pdf");
    xhr.upload.onprogress({ lengthComputable: true, loaded: 2, total: 4 });
    expect(onProgress).toHaveBeenCalledWith(50);
    xhr.status = 201; xhr.responseText = JSON.stringify(raw); xhr.onload();
    await expect(p).resolves.toMatchObject({ id: "d1", docType: "Drawings" });
  });

  test("rejects with the server's code and message on a duplicate", async () => {
    const p = store.uploadDocument("p1", new File([1], "x.pdf", { type: "application/pdf" }), "Drawings");
    const xhr = FakeXHR.last;
    xhr.status = 409; xhr.responseText = JSON.stringify({ detail: { code: "duplicate_document", message: "This appears to be the same file as first.pdf, uploaded earlier." } }); xhr.onload();
    await expect(p).rejects.toMatchObject({ code: "duplicate_document", status: 409 });
  });

  test("rejects readably when the network fails", async () => {
    const p = store.uploadDocument("p1", new File([1], "x.pdf", { type: "application/pdf" }), "Drawings");
    FakeXHR.last.onerror();
    await expect(p).rejects.toMatchObject({ code: "network" });
  });
});

describe("the other document methods", () => {
  let store;
  beforeEach(() => { store = createApiStore(); });
  afterEach(() => vi.unstubAllGlobals());

  test("listDocuments maps every row", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify([raw]), { status: 200 })));
    const docs = await store.listDocuments("p1");
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1/documents", expect.objectContaining({ credentials: "include" }));
    expect(docs[0].docType).toBe("Drawings");
  });

  test("setDocumentType PATCHes and deleteDocument DELETEs", async () => {
    const f = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ ...raw, doc_type: "Addendum" }), { status: 200 }))
                     .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", f);
    expect((await store.setDocumentType("d1", "Addendum")).docType).toBe("Addendum");
    expect(f.mock.calls[0][1].method).toBe("PATCH");
    await store.deleteDocument("d1");
    expect(f.mock.calls[1][0]).toBe("/api/documents/d1");
    expect(f.mock.calls[1][1].method).toBe("DELETE");
  });

  test("fetchDocumentFile returns a File named after the document", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob([new Uint8Array(3)]), { status: 200 })));
    const file = await store.fetchDocumentFile(mapDocument(raw));
    expect(file).toBeInstanceOf(File);
    expect(file.name).toBe("E-set.pdf");
    expect(file.type).toBe("application/pdf");
    expect(fetch).toHaveBeenCalledWith("/api/documents/d1/content", expect.objectContaining({ credentials: "include" }));
  });
});
