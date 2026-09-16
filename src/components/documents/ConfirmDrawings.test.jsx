/* ============================================================
   ConfirmDrawings.test.jsx — screen D, reading the set as the worker
   has read it (store.getProcessing). What matters: it lists every
   document with what the worker made of it -- read with a sheet count,
   still reading, or failed with the reason -- blocks starting without a
   drawing set, flags unrecognized documents in a Needs attention section
   above the table, lets the estimator correct a type before processing,
   and routes Start takeoff through store.startTakeoff, treating a run
   already in flight as already started and a set with nothing readable
   as a message to show, not a page to leave. There is no include/exclude
   control in this slice (see ConfirmDrawings.jsx's header) and no local
   file picker (a document is added through screen C, the only place one
   is actually persisted).
   ============================================================ */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";

const pdf = (name) => new File([new Uint8Array(2048)], name, { type: "application/pdf" });

let nextId = 0;
/** A document as the processing response describes it (mapProcessing's
 *  shape): what the worker made of it, not the upload record. Read by
 *  default, with sheets on a drawing set, so the gate the server keeps
 *  (a readable drawing) is open unless a test closes it. */
function docFrom(file, docType, extra = {}) {
  nextId += 1;
  return {
    id: `doc-${nextId}`,
    filename: file.name,
    docType,
    state: "read",
    reason: "",
    sheetCount: docType === "Drawings" ? 14 : 0,
    ...extra,
  };
}

function makeStore(docs = []) {
  return {
    getProcessing: vi.fn().mockResolvedValue({ documents: docs, run: null }),
    setDocumentType: vi.fn().mockResolvedValue(undefined),
    startTakeoff: vi.fn().mockResolvedValue({ runId: "r1" }),
    listScope: vi.fn().mockResolvedValue([]),
    decideScope: vi.fn(),
  };
}

const renderConfirm = (store) => {
  const tree = (
    <MemoryRouter initialEntries={["/projects/p1/documents/confirm"]}>
      <Routes>
        <Route path="/projects/:projectId/documents/confirm" element={<ConfirmDrawings store={store} />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
        <Route path="/projects/:projectId/documents" element={<p>upload</p>} />
      </Routes>
    </MemoryRouter>
  );
  return render(tree);
};

beforeEach(() => {
  nextId = 0;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ConfirmDrawings", () => {
  it("lists the uploaded documents and can start when a drawing set is present", async () => {
    const store = makeStore([
      docFrom(pdf("cd_biddrawings.pdf"), "Drawings"),
      docFrom(pdf("specs_part_1.pdf"), "Specifications"),
    ]);
    renderConfirm(store);

    expect(await screen.findByText("cd_biddrawings.pdf")).toBeTruthy();
    expect(screen.getByText("specs_part_1.pdf")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();
    expect(screen.queryByText(/no drawing set/i)).toBeNull();
    expect(store.getProcessing).toHaveBeenCalledWith("p1");
  });

  it("shows what the worker read per document -- sheet counts, reading, or the reason it failed", async () => {
    const store = makeStore([
      docFrom(pdf("cd_biddrawings.pdf"), "Drawings", { sheetCount: 14 }),
      docFrom(pdf("specs_part_1.pdf"), "Specifications", { sheetCount: 0 }),
      docFrom(pdf("addendum_1.pdf"), "Addendum", { state: "reading", sheetCount: 0 }),
      docFrom(pdf("locked.pdf"), "Drawings", { state: "failed", reason: "This file is password protected. Upload an unlocked copy.", sheetCount: 0 }),
    ]);
    renderConfirm(store);

    expect(await screen.findByText("Read · 14 sheets")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    expect(screen.getByText("This file is password protected. Upload an unlocked copy.")).toBeInTheDocument();
    // The state is a column with a heading, not a colour.
    expect(screen.getByRole("columnheader", { name: "State" })).toBeInTheDocument();
  });

  it("keeps polling while a document is still being read, and stops once nothing is", async () => {
    vi.useFakeTimers();
    const reading = docFrom(pdf("cd_biddrawings.pdf"), "Drawings", { state: "reading", sheetCount: 0 });
    const store = makeStore([reading]);
    store.getProcessing
      .mockResolvedValueOnce({ documents: [reading], run: null })
      .mockResolvedValueOnce({ documents: [reading], run: null })
      .mockResolvedValue({ documents: [{ ...reading, state: "read", sheetCount: 9 }], run: null });
    renderConfirm(store);

    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Reading…")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Read · 9 sheets")).toBeInTheDocument();
    const calls = store.getProcessing.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(6200));
    expect(store.getProcessing).toHaveBeenCalledTimes(calls);
  });

  it("mounts the scope section above the table", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    store.listScope.mockResolvedValue([
      { id: "s1", kind: "by_others", text: "Temporary power by GC.", editedText: null, status: "found", documentId: "d", documentFilename: "spec.pdf", page: 2, quote: "Temporary power by GC." },
    ]);
    renderConfirm(store);

    expect(await screen.findByText("1 statement found · 0 confirmed · 0 dismissed")).toBeInTheDocument();
    expect(store.listScope).toHaveBeenCalledWith("p1");
    const scope = screen.getByRole("heading", { name: "Scope stated in the documents" });
    const table = screen.getByRole("table");
    expect(scope.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("starts the takeoff through the store, then goes to processing", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    fireEvent.click(screen.getAllByRole("button", { name: /start takeoff/i })[0]);

    expect(store.startTakeoff).toHaveBeenCalledWith("p1");
    expect(await screen.findByText("processing")).toBeInTheDocument();
  });

  it("treats a run already in flight as started -- goes to processing, no error", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    store.startTakeoff.mockRejectedValue({ code: "run_in_flight", message: "A run is already in progress." });
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    fireEvent.click(screen.getAllByRole("button", { name: /start takeoff/i })[0]);

    expect(await screen.findByText("processing")).toBeInTheDocument();
    expect(screen.queryByText(/already in progress/i)).toBeNull();
  });

  it("stays and shows the server's message when nothing in the set could be read", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings", { state: "failed", reason: "Corrupt file.", sheetCount: 0 })]);
    store.startTakeoff.mockRejectedValue({
      code: "no_readable_drawings",
      message: "None of the uploaded documents could be read. Replace the drawing set and try again.",
    });
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    fireEvent.click(screen.getAllByRole("button", { name: /start takeoff/i })[0]);

    expect(await screen.findByRole("alert")).toHaveTextContent("None of the uploaded documents could be read");
    expect(screen.queryByText("processing")).toBeNull();
    // Still here, still able to try again once the set is fixed.
    screen.getAllByRole("button", { name: /start takeoff/i }).forEach((b) => expect(b).toBeEnabled());
  });

  it("shows any other failure's message inline and stays", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    store.startTakeoff.mockRejectedValue({ code: "network", message: "Couldn't reach the server. Check the connection and try again." });
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    fireEvent.click(screen.getAllByRole("button", { name: /start takeoff/i })[0]);

    expect(await screen.findByText(/Couldn't reach the server/)).toBeInTheDocument();
    expect(screen.queryByText("processing")).toBeNull();
  });

  it("blocks starting when nothing is typed Drawings", async () => {
    const store = makeStore([docFrom(pdf("specs_part_1.pdf"), "Specifications")]);
    renderConfirm(store);

    expect(await screen.findByText(/no drawing set/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();

    // Correcting the type to Drawings unblocks it, and persists.
    fireEvent.change(screen.getByLabelText(/type for specs_part_1\.pdf/i), { target: { value: "Drawings" } });
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();
    expect(store.setDocumentType).toHaveBeenCalledWith("doc-1", "Drawings");
  });

  it("flags an unrecognized document in a Needs attention section", async () => {
    const store = makeStore([
      docFrom(pdf("cd_biddrawings.pdf"), "Drawings"),
      docFrom(pdf("mystery_file.pdf"), "Other"),
    ]);
    renderConfirm(store);

    expect(await screen.findByText(/weren't recognized|wasn't recognized/i)).toBeTruthy();
    // Named in both the warning and the table row, so more than one match.
    expect(screen.getAllByText(/mystery_file\.pdf/).length).toBeGreaterThan(0);
  });

  it("shows an empty state when there is nothing to confirm", async () => {
    const store = makeStore([]);
    renderConfirm(store);
    expect(await screen.findByText(/no documents to confirm/i)).toBeTruthy();
  });

  it("shows a recoverable error, not an empty state, when the document list can't be loaded", async () => {
    const store = makeStore([]);
    store.getProcessing = vi.fn().mockRejectedValue(new Error("network"));
    renderConfirm(store);
    expect(await screen.findByText(/couldn't load this project's documents/i)).toBeTruthy();
    expect(screen.queryByText(/no documents to confirm/i)).toBeNull();
  });

  it("blocks processing, rather than merely flagging it, when nothing is a drawing set", async () => {
    // The four review labels are the vocabulary here too: an absent
    // drawing set is Missing information (no override), not Needs
    // attention, so it is counted as blocking and reported apart from
    // the amber rows.
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    fireEvent.change(screen.getByLabelText(/type for cd_biddrawings\.pdf/i), { target: { value: "Scope" } });

    expect(screen.getByText(/1 blocking/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();
    expect(screen.getByLabelText(/blocks processing/i)).toBeTruthy();
  });

  it("has no include/exclude control -- every listed document runs through the takeoff", async () => {
    const store = makeStore([
      docFrom(pdf("cd_biddrawings.pdf"), "Drawings"),
      docFrom(pdf("specs_part_1.pdf"), "Specifications"),
    ]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByText(/left out/i)).toBeNull();
    expect(screen.queryByText(/excluded document/i)).toBeNull();
    expect(screen.queryByText(/documents included/i)).toBeNull();
    // A plain count, not a fraction describing an inclusion decision.
    // toHaveTextContent (substring match) sidesteps the ambiguity of
    // getByText matching both this span and its parent footer div.
    expect(document.querySelector(".workspace-footer-status")).toHaveTextContent("2 documents");
  });

  it("offers a link back to screen C to add a document, not a local picker", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    const link = screen.getByRole("link", { name: /add documents/i });
    expect(link).toHaveAttribute("href", "/projects/p1/documents");
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.queryByRole("button", { name: /add files/i })).toBeNull();
  });

  it("reverts the select and surfaces the server's message when a type change fails, without un-counting the document", async () => {
    // Before this the failure was swallowed: the select showed the new
    // type, "Start takeoff" enabled on it, and the server still held
    // the old one -- processing would have read a type the estimator
    // never saw.
    const store = makeStore([docFrom(pdf("specs_part_1.pdf"), "Specifications")]);
    store.setDocumentType.mockRejectedValue({ code: "network", message: "Couldn't reach the server. Check the connection and try again." });
    renderConfirm(store);
    await screen.findByText("specs_part_1.pdf");
    screen.getAllByRole("button", { name: /start takeoff/i }).forEach((b) => expect(b).toBeDisabled());

    const select = screen.getByLabelText(/type for specs_part_1\.pdf/i);
    fireEvent.change(select, { target: { value: "Drawings" } });

    expect(await screen.findByText(/Couldn't reach the server/)).toBeInTheDocument();
    expect(select).toHaveValue("Specifications");
    expect(select).toHaveAccessibleDescription(/Couldn't reach the server/);
    // The server still holds no drawing set, so the gate stays shut.
    screen.getAllByRole("button", { name: /start takeoff/i }).forEach((b) => expect(b).toBeDisabled());
    // Still counted: one document, not zero.
    expect(document.querySelector(".workspace-footer-status")).toHaveTextContent("1 document");

    // A retry that succeeds clears the message.
    store.setDocumentType.mockResolvedValue(undefined);
    fireEvent.change(select, { target: { value: "Drawings" } });
    await waitFor(() => expect(screen.queryByText(/Couldn't reach the server/)).not.toBeInTheDocument());
    expect(select).toHaveValue("Drawings");
    screen.getAllByRole("button", { name: /start takeoff/i }).forEach((b) => expect(b).toBeEnabled());
  });

  it("counts only the lines it can confirm -- a deferred line is neither confirmed nor unresolved", async () => {
    const store = makeStore([
      docFrom(pdf("cd_biddrawings.pdf"), "Drawings"),
      docFrom(pdf("specs_part_1.pdf"), "Specifications"),
    ]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    // Five lines drawn; "Legends and scales" is deferred to processing.
    expect(screen.getByLabelText(/not known yet/i)).toBeInTheDocument();
    expect(screen.getByText("4 of 4 confirmed")).toBeInTheDocument();
    expect(screen.queryByText(/5 of 5/)).not.toBeInTheDocument();

    // And the attention phrasing uses the same denominator.
    fireEvent.change(screen.getByLabelText(/type for specs_part_1\.pdf/i), { target: { value: "Other" } });
    expect(await screen.findByText("2 of 4 need your attention")).toBeInTheDocument();
  });
});
