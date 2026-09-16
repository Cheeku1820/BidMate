/* ============================================================
   UploadDocuments.test.jsx — screen C as a view onto the API.
   A reload shows what was uploaded; a drop uploads with progress; the
   server's duplicate and unsupported copy lands on the row; remove asks
   first; the primary action needs a Drawings document.
   ============================================================ */
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import UploadDocuments from "./UploadDocuments.jsx";

// The content-sniff fallback (detected.source === "default") calls this
// for real otherwise -- an actual fetch to the standalone engine service
// that most of these tests have no reason to reach.
vi.mock("../../lib/engineClient.js", () => ({ classifyDoc: vi.fn().mockResolvedValue(null) }));
import { classifyDoc } from "../../lib/engineClient.js";

const pdf = (name, size = 1024) => new File([new Uint8Array(size)], name, { type: "application/pdf" });
const doc = (over = {}) => ({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 1024, status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z", ...over });

function makeStore(over = {}) {
  return {
    listDocuments: vi.fn().mockResolvedValue([]),
    uploadDocument: vi.fn(),
    setDocumentType: vi.fn(),
    deleteDocument: vi.fn().mockResolvedValue(null),
    ...over,
  };
}

const renderUpload = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/documents"]}>
      <Routes>
        <Route path="/projects/:projectId/documents" element={<UploadDocuments store={store} />} />
        <Route path="/projects/:projectId/documents/confirm" element={<p>confirm screen</p>} />
      </Routes>
    </MemoryRouter>,
  );

function drop(files) {
  const input = document.querySelector('input[type="file"]');
  Object.defineProperty(input, "files", { value: files, configurable: true });
  act(() => { input.dispatchEvent(new Event("change", { bubbles: true })); });
}

describe("UploadDocuments", () => {
  it("shows what was already uploaded, from the API, on mount", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    expect(await screen.findByText("E-set.pdf")).toBeInTheDocument();
    // Status "uploaded" is the read-in-flight state, same as "processing"
    // -- see the "renders processing and processed..." test below. It is
    // not "Uploaded": B2's automatic read means this row is about to be
    // read, not done.
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    expect(store.listDocuments).toHaveBeenCalledWith("p1");
  });

  it("renders processing and processed documents by their own state, not as failed", async () => {
    // B1 residual I5: before this fix, any status other than the literal
    // "uploaded" rendered in the failed tone with the generic fallback
    // copy -- so the day the worker started writing "processing" and
    // "processed" (docs/specs/engine-behind-the-api.md), every one of
    // those documents would have looked like a read failure.
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([
        doc({ id: "d1", filename: "a.pdf", status: "processing" }),
        doc({ id: "d2", filename: "b.pdf", status: "processed" }),
        doc({ id: "d3", filename: "c.pdf", status: "failed", error: "Couldn't read this file." }),
      ]),
    });
    renderUpload(store);
    expect(await screen.findByText("Reading…")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(screen.getByText("Couldn't read this file.")).toBeInTheDocument();
    expect(screen.queryAllByText(/couldn't be read/i)).toHaveLength(0);
    // b.pdf (processed, Drawings) satisfies the drawing-set gate on its
    // own -- neither a and b's non-failed states nor c's failure should
    // block continuing.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());
  });

  it("uploads a dropped PDF with progress and settles to Uploaded", async () => {
    let progress;
    const store = makeStore({
      uploadDocument: vi.fn((projectId, file, docType, opts) => { progress = opts.onProgress; return new Promise(() => {}); }),
    });
    renderUpload(store);
    drop([pdf("E-set.pdf")]);
    expect(await screen.findByText(/Uploading/)).toBeInTheDocument();
    act(() => progress(42));
    // The percentage is a nested span (hidden from the live region --
    // see the state cell), so match on the whole cell's text.
    expect(screen.getByText(/Uploading…/).closest("td")).toHaveTextContent("Uploading… 42%");
    expect(store.uploadDocument).toHaveBeenCalledWith("p1", expect.any(File), "Drawings", expect.any(Object));
  });

  it("shows the server's duplicate copy on the row and does not list it as uploaded", async () => {
    const store = makeStore({
      uploadDocument: vi.fn().mockRejectedValue({ code: "duplicate_document", message: "This appears to be the same file as first.pdf, uploaded earlier. Remove one copy or upload a different file.", status: 409 }),
    });
    renderUpload(store);
    drop([pdf("second.pdf")]);
    expect(await screen.findByText(/same file as first.pdf/)).toBeInTheDocument();
    expect(screen.queryByText("Uploaded")).not.toBeInTheDocument();
    // The top bar and the footer both carry a "Review detected drawings"
    // control (matching ConfirmDrawings' pair) -- both have to reflect
    // the block.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
  });

  it("refuses a non-PDF before calling the API", async () => {
    const store = makeStore();
    renderUpload(store);
    drop([new File([1], "notes.docx", { type: "text/plain" })]);
    expect(await screen.findByText(/isn't a PDF/)).toBeInTheDocument();
    expect(store.uploadDocument).not.toHaveBeenCalled();
  });

  it("changes the type through the API", async () => {
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc()]),
      setDocumentType: vi.fn().mockResolvedValue(doc({ docType: "Addendum" })),
    });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    await waitFor(() => expect(store.setDocumentType).toHaveBeenCalledWith("d1", "Addendum"));
  });

  it("asks before removing, then deletes through the API", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getByRole("button", { name: /remove E-set.pdf/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/remove E-set.pdf/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /^remove$/i }));
    await waitFor(() => expect(store.deleteDocument).toHaveBeenCalledWith("d1"));
    await waitFor(() => expect(screen.queryByText("E-set.pdf")).not.toBeInTheDocument());
  });

  it("blocks continuing until at least one document is typed Drawings", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc({ docType: "Specifications" })]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
  });

  it("continues to confirm when a Drawings document exists", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getAllByRole("button", { name: /review detected drawings/i })[0]);
    expect(await screen.findByText("confirm screen")).toBeInTheDocument();
  });

  it("resolves a drop to reading, swapping the row's key to the server id and enabling the primary action", async () => {
    const store = makeStore({
      uploadDocument: vi.fn().mockResolvedValue(doc()),
    });
    renderUpload(store);
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
    drop([pdf("E-set.pdf")]);
    await waitFor(() => expect(screen.getByText("Reading…")).toBeInTheDocument());
    // A row that's reading, not failed and not still uploading, already
    // satisfies the drawing-set gate.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());
    // The row now carries the server's id -- removing it asks first,
    // same as a row that arrived from the initial list.
    fireEvent.click(screen.getByRole("button", { name: /remove E-set.pdf/i }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("aborts the in-flight upload when removed, and a later resolve does not resurrect the row", async () => {
    let resolveUpload;
    const abort = vi.fn();
    const store = makeStore({
      uploadDocument: vi.fn(() => {
        const p = new Promise((resolve) => { resolveUpload = resolve; });
        p.abort = abort;
        return p;
      }),
    });
    renderUpload(store);
    drop([pdf("E-set.pdf")]);
    expect(await screen.findByText(/Uploading/)).toBeInTheDocument();
    // No dialog for a row that hasn't reached the server yet.
    fireEvent.click(screen.getByRole("button", { name: /remove E-set.pdf/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("E-set.pdf")).not.toBeInTheDocument();
    expect(abort).toHaveBeenCalled();
    // The server finishes anyway (the abort raced it) -- the row must
    // not come back.
    await act(async () => { resolveUpload(doc()); });
    expect(screen.queryByText("E-set.pdf")).not.toBeInTheDocument();
  });

  it("shows a recovery message when the initial list fails to load, with a working retry", async () => {
    const listDocuments = vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce([doc()]);
    const store = makeStore({ listDocuments });
    renderUpload(store);
    expect(await screen.findByText(/couldn't load this project's documents/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("E-set.pdf")).toBeInTheDocument();
    expect(listDocuments).toHaveBeenCalledTimes(2);
  });

  it("reverts the type and surfaces the server's message when a retype fails, without un-counting the document, and clears it on the next successful write", async () => {
    const setDocumentType = vi
      .fn()
      .mockRejectedValueOnce({ code: "request_failed", message: "Couldn't change the type. Try again." })
      .mockResolvedValueOnce(doc({ docType: "Addendum" }));
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]), setDocumentType });
    renderUpload(store);
    await screen.findByText("E-set.pdf");

    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    expect(await screen.findByText("Couldn't change the type. Try again.")).toBeInTheDocument();
    expect(screen.getByLabelText(/type for E-set.pdf/i)).toHaveValue("Drawings");
    // The document still counts as ready -- one failed retype must not
    // un-count an already-uploaded document or close the drawing-set gate.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    await waitFor(() => expect(screen.queryByText("Couldn't change the type. Try again.")).not.toBeInTheDocument());
    expect(screen.getByText("Reading…")).toBeInTheDocument();
  });

  it("keeps the row and surfaces the server's message when a delete fails, without disabling continuing", async () => {
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc()]),
      deleteDocument: vi.fn().mockRejectedValue({ code: "request_failed", message: "Couldn't remove this document. Try again." }),
    });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getByRole("button", { name: /remove E-set.pdf/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /^remove$/i }));
    expect(await screen.findByText("Couldn't remove this document. Try again.")).toBeInTheDocument();
    expect(screen.getByText("E-set.pdf")).toBeInTheDocument();
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());
  });

  it("forwards a type change made while still uploading, once the document has an id", async () => {
    let resolveUpload;
    const store = makeStore({
      uploadDocument: vi.fn(() => new Promise((resolve) => { resolveUpload = resolve; })),
      setDocumentType: vi.fn().mockResolvedValue(doc({ docType: "Addendum" })),
    });
    renderUpload(store);
    drop([pdf("E-set.pdf")]);
    await screen.findByText(/Uploading/);
    // The upload's form data already carried "Drawings" -- this change
    // happens before the server has anything to PATCH.
    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    expect(store.setDocumentType).not.toHaveBeenCalled();

    await act(async () => { resolveUpload(doc({ docType: "Drawings" })); });

    await waitFor(() => expect(store.setDocumentType).toHaveBeenCalledWith("d1", "Addendum"));
    expect(await screen.findByText("Reading…")).toBeInTheDocument();
    expect(screen.getByLabelText(/type for E-set.pdf/i)).toHaveValue("Addendum");
  });

  it("still loads the document list under StrictMode's simulated double-mount", async () => {
    // src/main.jsx renders the whole app inside <React.StrictMode>,
    // which in development double-invokes an effect's mount, cleanup,
    // then mount again -- this is the case aliveRef has to survive.
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    render(
      <StrictMode>
        <MemoryRouter initialEntries={["/projects/p1/documents"]}>
          <Routes>
            <Route path="/projects/:projectId/documents" element={<UploadDocuments store={store} />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>,
    );
    expect(await screen.findByText("E-set.pdf")).toBeInTheDocument();
  });

  it("renders a document the server marks failed as failed, with the server's reason, and does not count it", async () => {
    // B2's worker reports back through `status`/`error`. Before this,
    // the row state was hard-coded "ready" and a failed document
    // rendered as "Uploaded" -- silence reading as completeness.
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([
        doc({ id: "d-ok", filename: "E-set.pdf", status: "uploaded" }),
        doc({ id: "d-bad", filename: "E-addendum.pdf", docType: "Drawings", status: "failed", error: "The file is password protected. Upload an unlocked copy." }),
      ]),
    });
    renderUpload(store);
    expect(await screen.findByText("E-addendum.pdf")).toBeInTheDocument();

    const reason = screen.getByText("The file is password protected. Upload an unlocked copy.");
    expect(reason).toHaveClass("upload-status--unsupported");
    expect(screen.getAllByText("Reading…")).toHaveLength(1);
    // Counted where it belongs: with the files that need attention,
    // not with the readable ones.
    expect(screen.getByText(/1 need attention/)).toBeInTheDocument();
  });

  it("gives a failed document a plain sentence when the server sends no reason", async () => {
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc({ status: "failed", error: "" })]),
    });
    renderUpload(store);
    expect(await screen.findByText("E-set.pdf")).toBeInTheDocument();
    expect(screen.getByText(/couldn't be read/i)).toHaveClass("upload-status--unsupported");
    expect(screen.queryByText("Uploaded")).not.toBeInTheDocument();
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
  });

  it("announces a row's state through a polite live region, with the progress figure kept out of it", async () => {
    let progress;
    const store = makeStore({
      uploadDocument: vi.fn((projectId, file, docType, opts) => { progress = opts.onProgress; return new Promise(() => {}); }),
    });
    renderUpload(store);
    drop([pdf("E-set.pdf")]);
    const cell = (await screen.findByText(/Uploading…/)).closest("td");
    expect(cell).toHaveAttribute("aria-live", "polite");
    expect(cell).toHaveAttribute("aria-atomic", "true");
    act(() => progress(42));
    // The number is visible but aria-hidden: a region that re-announces
    // every tick is one nobody keeps switched on.
    expect(within(cell).getByText("42%")).toHaveAttribute("aria-hidden", "true");
  });

  it("keeps the filename's guess when the content-based second look cannot reach the engine", async () => {
    classifyDoc.mockRejectedValueOnce(new Error("engine unreachable"));
    const store = makeStore({
      // "scan.pdf" carries no type hint, so detectDocTypeInfo falls to
      // its default (Drawings) and the content-based second look runs.
      uploadDocument: vi.fn().mockResolvedValue(doc({ filename: "scan.pdf", docType: "Drawings" })),
    });
    renderUpload(store);
    drop([pdf("scan.pdf")]);
    await waitFor(() => expect(screen.getByText("Reading…")).toBeInTheDocument());
    await waitFor(() => expect(classifyDoc).toHaveBeenCalled());
    // No unhandled rejection, no retype, the guess stands.
    expect(store.setDocumentType).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/type for scan.pdf/i)).toHaveValue("Drawings");
    expect(screen.getByText("Detected")).toBeInTheDocument();
  });

  it("surfaces a failed write of the content-based type on the row and keeps the type the server holds", async () => {
    classifyDoc.mockResolvedValueOnce("Specifications");
    const store = makeStore({
      uploadDocument: vi.fn().mockResolvedValue(doc({ filename: "scan.pdf", docType: "Drawings" })),
      setDocumentType: vi.fn().mockRejectedValue({ code: "network", message: "Couldn't reach the server. Check the connection and try again." }),
    });
    renderUpload(store);
    drop([pdf("scan.pdf")]);
    await waitFor(() => expect(store.setDocumentType).toHaveBeenCalledWith("d1", "Specifications"));
    expect(await screen.findByText(/Couldn't reach the server/)).toBeInTheDocument();
    // The select shows what the server holds, not what the write
    // hoped for, and the row is still counted -- a failed retype does
    // not knock a reading, Drawings-typed row out of the gate.
    expect(screen.getByLabelText(/type for scan.pdf/i)).toHaveValue("Drawings");
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());
  });
});
