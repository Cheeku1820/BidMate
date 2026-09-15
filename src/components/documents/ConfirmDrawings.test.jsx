/* ============================================================
   ConfirmDrawings.test.jsx — screen D, reading the real uploaded set
   from the API (store.listDocuments). What matters: it groups the
   documents by type, blocks starting without a drawing set, flags
   unrecognized documents in a Needs attention section above the table,
   and lets the estimator correct a type before processing. There is no
   include/exclude control in this slice (a prior version had one, but
   it never reached processing -- see ConfirmDrawings.jsx's header) and
   no local file picker (a document is added through screen C, which is
   the only place one is actually persisted).
   ============================================================ */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";

const pdf = (name) => new File([new Uint8Array(2048)], name, { type: "application/pdf" });

let nextId = 0;
/** A stored document as the API would return it (mapDocument's shape). */
function docFrom(file, docType) {
  nextId += 1;
  return {
    id: `doc-${nextId}`,
    projectId: "p1",
    filename: file.name,
    docType,
    sizeBytes: file.size,
    status: "uploaded",
    error: "",
    createdAt: "2026-09-15T00:00:00Z",
  };
}

function makeStore(docs = []) {
  return {
    listDocuments: vi.fn().mockResolvedValue(docs),
    setDocumentType: vi.fn().mockResolvedValue(undefined),
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
    store.listDocuments = vi.fn().mockRejectedValue(new Error("network"));
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
});
