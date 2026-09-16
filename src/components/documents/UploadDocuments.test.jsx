/* ============================================================
   UploadDocuments.test.jsx — screen C as a view onto the API.
   A reload shows what was uploaded; a drop uploads with progress; the
   server's duplicate and unsupported copy lands on the row; remove asks
   first; the primary action needs a Drawings document.
   ============================================================ */
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import UploadDocuments from "./UploadDocuments.jsx";

const pdf = (name, size = 1024) => new File([new Uint8Array(size)], name, { type: "application/pdf" });
const doc = (over = {}) => ({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 1024, status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z", ...over });

function makeStore(over = {}) {
  return {
    listDocuments: vi.fn().mockResolvedValue([]),
    uploadDocument: vi.fn(),
    setDocumentType: vi.fn(),
    deleteDocument: vi.fn().mockResolvedValue(null),
    // A default every "reading" row's poll effect can call safely even
    // when a test doesn't care about polling -- an empty document list
    // matches nothing, so rows are left exactly as they were.
    getProcessing: vi.fn().mockResolvedValue({ documents: [], run: null }),
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
  afterEach(() => {
    // A test that throws before reaching its own vi.useRealTimers() call
    // must not leave fake timers armed for the next test in the file.
    vi.useRealTimers();
  });

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
    // b.pdf (processed -> read, Drawings) is what actually opens the
    // drawing-set gate here -- a.pdf's "reading" state doesn't block it,
    // but doesn't count toward it either, since the worker hasn't
    // produced its sheets yet.
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
    // "processed" -- not merely uploaded -- so the row is "read" and the
    // gate is legitimately open: a document still being read hasn't
    // produced sheets yet (see the "resolves a drop to reading" test
    // below), so clicking this control would do nothing if it were.
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc({ status: "processed" })]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getAllByRole("button", { name: /review detected drawings/i })[0]);
    expect(await screen.findByText("confirm screen")).toBeInTheDocument();
  });

  it("resolves a drop to reading, swapping the row's key to the server id, without yet enabling the primary action", async () => {
    const store = makeStore({
      uploadDocument: vi.fn().mockResolvedValue(doc()),
    });
    renderUpload(store);
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
    drop([pdf("E-set.pdf")]);
    await waitFor(() => expect(screen.getByText("Reading…")).toBeInTheDocument());
    // A row that's still being read hasn't produced sheets yet -- the
    // server's own read_drawings query only counts a document once it's
    // processed, and the gate mirrors that rather than the client's
    // optimistic guess. Reading isn't blocked (it isn't in
    // BLOCKED_STATES), it just doesn't count yet either.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
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
    // "processed" -- read, not merely reading -- so the gate starts open
    // and the assertion below actually exercises "a failed retype must
    // not close it", rather than a gate that was never open to begin
    // with.
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc({ status: "processed" })]), setDocumentType });
    renderUpload(store);
    await screen.findByText("E-set.pdf");

    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    expect(await screen.findByText("Couldn't change the type. Try again.")).toBeInTheDocument();
    expect(screen.getByLabelText(/type for E-set.pdf/i)).toHaveValue("Drawings");
    // The document still counts as read -- one failed retype must not
    // un-count an already-read document or close the drawing-set gate.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeEnabled());

    fireEvent.change(screen.getByLabelText(/type for E-set.pdf/i), { target: { value: "Addendum" } });
    await waitFor(() => expect(screen.queryByText("Couldn't change the type. Try again.")).not.toBeInTheDocument());
    expect(screen.getByLabelText(/type for E-set.pdf/i)).toHaveValue("Addendum");
    // A retype doesn't touch read state -- the row was already read and
    // stays read.
    expect(screen.getByText("Read")).toBeInTheDocument();
  });

  it("keeps the row and surfaces the server's message when a delete fails, without disabling continuing", async () => {
    // "processed" so the gate starts open -- this test's point is that a
    // failed delete doesn't close it, which needs it open beforehand.
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc({ status: "processed" })]),
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

  it("polls processing while a document is being read and shows the sheet count once read", async () => {
    vi.useFakeTimers();
    const getProcessing = vi
      .fn()
      .mockResolvedValueOnce({ documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "reading", reason: "", sheetCount: 0 }], run: null })
      .mockResolvedValue({ documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 14 }], run: null });
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc({ id: "d1", filename: "a.pdf", status: "processing" })]),
      getProcessing,
    });
    renderUpload(store);
    // React's own scheduling (outside this test's explicit act calls)
    // leans on timers that useFakeTimers also replaces, so the initial
    // mount has to be flushed the same way the polling ticks below are.
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Read · 14 sheets")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(getProcessing).toHaveBeenCalledTimes(2); // polling stops once nothing is reading
  });

  it("clears a stale row error once a later poll reports the document read", async () => {
    // Before polling existed, only a full reload could self-heal a row
    // still showing a failed retype's message -- the poll merge has to
    // do the same self-heal, or a fixed document would go on looking
    // broken forever.
    vi.useFakeTimers();
    const getProcessing = vi
      .fn()
      .mockResolvedValueOnce({ documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "reading", reason: "", sheetCount: 0 }], run: null })
      .mockResolvedValue({ documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 3 }], run: null });
    const setDocumentType = vi.fn().mockRejectedValue({ code: "request_failed", message: "Couldn't change the type. Try again." });
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc({ id: "d1", filename: "a.pdf", status: "processing" })]),
      setDocumentType,
      getProcessing,
    });
    renderUpload(store);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Reading…")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/type for a\.pdf/i), { target: { value: "Addendum" } });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Couldn't change the type. Try again.")).toBeInTheDocument();

    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Read · 3 sheets")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't change the type. Try again.")).not.toBeInTheDocument();
  });

  it("moves a reading row to failed when a later poll reports the worker couldn't read it", async () => {
    vi.useFakeTimers();
    const getProcessing = vi
      .fn()
      .mockResolvedValueOnce({ documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "reading", reason: "", sheetCount: 0 }], run: null })
      .mockResolvedValue({
        documents: [{ id: "d1", filename: "a.pdf", docType: "Drawings", state: "failed", reason: "The file is password protected. Upload an unlocked copy.", sheetCount: 0 }],
        run: null,
      });
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([doc({ id: "d1", filename: "a.pdf", status: "processing" })]),
      getProcessing,
    });
    renderUpload(store);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("The file is password protected. Upload an unlocked copy.")).toBeInTheDocument();
    // Failed is a blocked state -- once the poll reports it, the gate
    // must close the same as any other failed document.
    screen.getAllByRole("button", { name: /review detected drawings/i }).forEach((b) => expect(b).toBeDisabled());
  });

  it("shows a failed read's reason and keeps the row removable", async () => {
    const store = makeStore({
      listDocuments: vi.fn().mockResolvedValue([
        doc({ id: "d1", filename: "a.pdf", status: "failed", error: "Couldn't read — the file is password protected. Upload an unlocked copy." }),
      ]),
    });
    renderUpload(store);
    expect(await screen.findByText(/password protected/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /remove a\.pdf/i })).toBeInTheDocument();
  });
});
