/* ============================================================
   ConfirmDrawings.test.jsx — screen D, now reading the real uploaded
   set from the API (store.listDocuments) instead of a browser-held
   file map. What matters: it groups the documents by type,
   blocks starting without a drawing set, flags unrecognized documents
   in a Needs attention section above the table, and lets the estimator
   correct a type or leave a document out before processing.
   ============================================================ */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";
import * as engineClient from "../../lib/engineClient.js";

// The mount-time content-sniff fallback would otherwise reach the real
// standalone engine service; none of these tests seed a document that
// should trigger it (see docFrom below), but stubbing it keeps every
// test hermetic regardless.
vi.mock("../../lib/engineClient.js", () => ({ classifyDoc: vi.fn().mockResolvedValue(null) }));

/** Puts files through the hidden picker the way the estimator's own
 *  selection would, one selection at a time. */
function choose(files) {
  const input = document.querySelector('input[type="file"]');
  Object.defineProperty(input, "files", { value: files, configurable: true });
  act(() => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

const pdf = (name) => new File([new Uint8Array(2048)], name, { type: "application/pdf" });

let nextId = 0;
/** A stored document as the API would return it (mapDocument's shape),
 *  built from a File the way the old seed()'s {file, docType} pairs
 *  were. None of these filenames are "uninformative" by
 *  detectDocTypeInfo, so none of them trigger the mount-time
 *  fetchDocumentFile sniff. */
function docFrom(file, docType) {
  nextId += 1;
  return {
    id: `doc-${nextId}`,
    projectId: "p1",
    filename: file.name,
    docType,
    sizeBytes: file.size,
    sha256: `sha-${nextId}`,
    status: "uploaded",
    error: "",
    createdAt: "2026-09-15T00:00:00Z",
  };
}

function makeStore(docs = []) {
  return {
    listDocuments: vi.fn().mockResolvedValue(docs),
    setDocumentType: vi.fn().mockResolvedValue(undefined),
    fetchDocumentFile: vi.fn(),
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
    expect(store.listDocuments).toHaveBeenCalledWith("p1");
  });

  it("blocks starting when nothing is typed Drawings", async () => {
    const store = makeStore([docFrom(pdf("specs_part_1.pdf"), "Specifications")]);
    renderConfirm(store);

    expect(await screen.findByText(/no drawing set/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();

    // Correcting the type to Drawings unblocks it.
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
    // A document already typed Other is a real, already-made decision --
    // the mount-time sniff must never second-guess it.
    expect(store.fetchDocumentFile).not.toHaveBeenCalled();
  });

  it("excluding the only drawing set blocks starting", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    expect(await screen.findByText("cd_biddrawings.pdf")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /include cd_biddrawings\.pdf/i }));
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();
    expect(screen.getByText(/no drawing set/i)).toBeTruthy();
  });

  it("shows an empty state when there is nothing to confirm", async () => {
    const store = makeStore([]);
    renderConfirm(store);
    expect(await screen.findByText(/no documents to confirm/i)).toBeTruthy();
  });

  it("shows a recoverable error, not an empty state, when the document list can't be loaded", async () => {
    const store = makeStore([]);
    store.listDocuments = vi.fn().mockRejectedValue(new Error("network"));
    renderConfirm(store);
    expect(await screen.findByText(/couldn't load this project's documents/i)).toBeTruthy();
    expect(screen.queryByText(/no documents to confirm/i)).toBeNull();
  });
});

describe("ConfirmDrawings — adding files after the first upload", () => {
  it("adds a file and types it from its name, without leaving the screen", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([pdf("specs_part_1.pdf")]);

    expect(screen.getByText("specs_part_1.pdf")).toBeTruthy();
    expect(screen.getByLabelText(/type for specs_part_1\.pdf/i)).toHaveValue("Specifications");
    // Still on the confirm screen, with the original file's type intact.
    expect(screen.getByLabelText(/type for cd_biddrawings\.pdf/i)).toHaveValue("Drawings");
  });

  it("reads the content to type a file whose name says nothing", async () => {
    // detectDocTypeInfo falls back to Drawings for an uninformative name;
    // the content look-up is what corrects it, exactly as on upload.
    engineClient.classifyDoc.mockResolvedValueOnce("Specifications");
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([pdf("00123.pdf")]);
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Drawings");

    await act(async () => {});
    expect(engineClient.classifyDoc).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Specifications");
  });

  it("keeps a type the estimator corrected while the look-up was in flight", async () => {
    let settle;
    engineClient.classifyDoc.mockReturnValueOnce(
      new Promise((resolve) => {
        settle = resolve;
      }),
    );
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([pdf("00123.pdf")]);
    fireEvent.change(screen.getByLabelText(/type for 00123\.pdf/i), { target: { value: "Scope" } });

    await act(async () => {
      settle("Specifications");
    });

    // The person's own answer wins over the one that arrived late.
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Scope");
  });

  it("refuses a duplicate and a non-PDF by name, and counts exactly what it lists", async () => {
    // The heading and the list are two renderings of one array. They
    // disagreed in the running app while that array was being filled
    // inside a state updater; this pins that they agree.
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([pdf("cd_biddrawings.pdf"), new File(["x"], "notes.txt", { type: "text/plain" })]);

    const notice = screen.getByText(/files weren't added/i).closest(".warncard");
    expect(within(notice).getAllByRole("listitem")).toHaveLength(2);
    expect(notice).toHaveTextContent("2 files weren't added");
    expect(within(notice).getByText(/cd_biddrawings\.pdf is already in this list/i)).toBeTruthy();
    expect(within(notice).getByText(/notes\.txt isn't a PDF/i)).toBeTruthy();
  });

  it("catches two copies of one file inside a single selection", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([pdf("addendum_01.pdf"), pdf("addendum_01.pdf")]);

    expect(screen.getAllByText("addendum_01.pdf")).toHaveLength(1);
    expect(screen.getByText(/1 file wasn't added/i)).toBeTruthy();
  });

  it("lists two files that failed the same way as two lines, not one", async () => {
    // Identical failures produce identical sentences, which is why the
    // list is keyed by position rather than by its text.
    const txt = (name) => new File(["x"], name, { type: "text/plain" });
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    // Sequenced, so the second list reconciles against the first rather
    // than mounting fresh -- which is where a duplicate key does damage.
    choose([txt("a.txt")]);
    choose([txt("notes.txt"), txt("notes.txt")]);

    const notice = screen.getByText(/files weren't added/i).closest(".warncard");
    expect(notice).toHaveTextContent("2 files weren't added");
    expect(within(notice).getAllByRole("listitem")).toHaveLength(2);
  });

  it("clears the previous refusals when the next selection succeeds", async () => {
    const store = makeStore([docFrom(pdf("cd_biddrawings.pdf"), "Drawings")]);
    renderConfirm(store);
    await screen.findByText("cd_biddrawings.pdf");

    choose([new File(["x"], "notes.txt", { type: "text/plain" })]);
    expect(screen.getByText(/1 file wasn't added/i)).toBeTruthy();

    choose([pdf("addendum_01.pdf")]);
    // The notice explained one action; it must not outlive it.
    expect(screen.queryByText(/wasn't added|weren't added/i)).toBeNull();
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
});
