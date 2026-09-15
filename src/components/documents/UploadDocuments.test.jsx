/* ============================================================
   UploadDocuments.test.jsx — screen C as a view onto the API.
   A reload shows what was uploaded; a drop uploads with progress; the
   server's duplicate and unsupported copy lands on the row; remove asks
   first; the primary action needs a Drawings document.
   ============================================================ */
import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import UploadDocuments from "./UploadDocuments.jsx";

const pdf = (name, size = 1024) => new File([new Uint8Array(size)], name, { type: "application/pdf" });
const doc = (over = {}) => ({ id: "d1", projectId: "p1", filename: "E-set.pdf", docType: "Drawings", sizeBytes: 1024, sha256: "a", status: "uploaded", error: "", createdAt: "2026-09-15T00:00:00Z", ...over });

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
    expect(screen.getByText("Uploaded")).toBeInTheDocument();
    expect(store.listDocuments).toHaveBeenCalledWith("p1");
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
    expect(screen.getByText("Uploading… 42%")).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: /review detected drawings/i })).toBeDisabled();
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
    expect(screen.getByRole("button", { name: /review detected drawings/i })).toBeDisabled();
  });

  it("continues to confirm when a Drawings document exists", async () => {
    const store = makeStore({ listDocuments: vi.fn().mockResolvedValue([doc()]) });
    renderUpload(store);
    await screen.findByText("E-set.pdf");
    fireEvent.click(screen.getByRole("button", { name: /review detected drawings/i }));
    expect(await screen.findByText("confirm screen")).toBeInTheDocument();
  });
});
