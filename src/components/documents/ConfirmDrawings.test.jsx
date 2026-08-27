/* ============================================================
   ConfirmDrawings.test.jsx — screen D, now reflecting the real uploaded
   set. What matters: it groups the documents by type, blocks starting
   without a drawing set, flags unrecognized documents in a Needs
   attention section above the table, and lets the estimator correct a
   type or leave a document out before processing.
   ============================================================ */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";
import { setUploadedFiles } from "../../lib/uploadedFiles.js";
import * as engineClient from "../../lib/engineClient.js";

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

function seed(files) {
  setUploadedFiles("p1", files);
}

const renderConfirm = () => {
  const tree = (
    <MemoryRouter initialEntries={["/projects/p1/documents/confirm"]}>
      <Routes>
        <Route path="/projects/:projectId/documents/confirm" element={<ConfirmDrawings />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
        <Route path="/projects/:projectId/documents" element={<p>upload</p>} />
      </Routes>
    </MemoryRouter>
  );
  return render(tree);
};

beforeEach(() => setUploadedFiles("p1", []));

describe("ConfirmDrawings", () => {
  it("lists the uploaded documents and can start when a drawing set is present", () => {
    seed([
      { file: pdf("cd_biddrawings.pdf"), docType: "Drawings" },
      { file: pdf("specs_part_1.pdf"), docType: "Specifications" },
    ]);
    renderConfirm();

    expect(screen.getByText("cd_biddrawings.pdf")).toBeTruthy();
    expect(screen.getByText("specs_part_1.pdf")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();
    expect(screen.queryByText(/no drawing set/i)).toBeNull();
  });

  it("blocks starting when nothing is typed Drawings", () => {
    seed([{ file: pdf("specs_part_1.pdf"), docType: "Specifications" }]);
    renderConfirm();

    expect(screen.getByText(/no drawing set/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();

    // Correcting the type to Drawings unblocks it.
    fireEvent.change(screen.getByLabelText(/type for specs_part_1\.pdf/i), { target: { value: "Drawings" } });
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();
  });

  it("flags an unrecognized document in a Needs attention section", () => {
    seed([
      { file: pdf("cd_biddrawings.pdf"), docType: "Drawings" },
      { file: pdf("mystery_file.pdf"), docType: "Other" },
    ]);
    renderConfirm();

    expect(screen.getByText(/weren't recognized|wasn't recognized/i)).toBeTruthy();
    // Named in both the warning and the table row, so more than one match.
    expect(screen.getAllByText(/mystery_file\.pdf/).length).toBeGreaterThan(0);
  });

  it("excluding the only drawing set blocks starting", async () => {
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeEnabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /include cd_biddrawings\.pdf/i }));
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();
    expect(screen.getByText(/no drawing set/i)).toBeTruthy();
  });

  it("shows an empty state when there is nothing to confirm", () => {
    renderConfirm();
    expect(screen.getByText(/no documents to confirm/i)).toBeTruthy();
  });
});

describe("ConfirmDrawings — adding files after the first upload", () => {
  it("adds a file and types it from its name, without leaving the screen", () => {
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    choose([pdf("specs_part_1.pdf")]);

    expect(screen.getByText("specs_part_1.pdf")).toBeTruthy();
    expect(screen.getByLabelText(/type for specs_part_1\.pdf/i)).toHaveValue("Specifications");
    // Still on the confirm screen, with the original file's type intact.
    expect(screen.getByLabelText(/type for cd_biddrawings\.pdf/i)).toHaveValue("Drawings");
  });

  it("reads the content to type a file whose name says nothing", async () => {
    // detectDocTypeInfo falls back to Drawings for an uninformative name;
    // the content look-up is what corrects it, exactly as on upload.
    const spy = vi.spyOn(engineClient, "classifyDoc").mockResolvedValue("Specifications");
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    choose([pdf("00123.pdf")]);
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Drawings");

    await act(async () => {});
    expect(spy).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Specifications");
    spy.mockRestore();
  });

  it("keeps a type the estimator corrected while the look-up was in flight", async () => {
    let settle;
    const spy = vi
      .spyOn(engineClient, "classifyDoc")
      .mockReturnValue(new Promise((resolve) => {
        settle = resolve;
      }));
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    choose([pdf("00123.pdf")]);
    fireEvent.change(screen.getByLabelText(/type for 00123\.pdf/i), { target: { value: "Scope" } });

    await act(async () => {
      settle("Specifications");
    });

    // The person's own answer wins over the one that arrived late.
    expect(screen.getByLabelText(/type for 00123\.pdf/i)).toHaveValue("Scope");
    spy.mockRestore();
  });

  it("refuses a duplicate and a non-PDF by name, and counts exactly what it lists", () => {
    // The heading and the list are two renderings of one array. They
    // disagreed in the running app while that array was being filled
    // inside a state updater; this pins that they agree.
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    choose([pdf("cd_biddrawings.pdf"), new File(["x"], "notes.txt", { type: "text/plain" })]);

    const notice = screen.getByText(/files weren't added/i).closest(".warncard");
    expect(within(notice).getAllByRole("listitem")).toHaveLength(2);
    expect(notice).toHaveTextContent("2 files weren't added");
    expect(within(notice).getByText(/cd_biddrawings\.pdf is already in this list/i)).toBeTruthy();
    expect(within(notice).getByText(/notes\.txt isn't a PDF/i)).toBeTruthy();
  });

  it("catches two copies of one file inside a single selection", () => {
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    choose([pdf("addendum_01.pdf"), pdf("addendum_01.pdf")]);

    expect(screen.getAllByText("addendum_01.pdf")).toHaveLength(1);
    expect(screen.getByText(/1 file wasn't added/i)).toBeTruthy();
  });

  it("lists two files that failed the same way as two lines, not one", () => {
    // Identical failures produce identical sentences, which is why the
    // list is keyed by position rather than by its text.
    const txt = (name) => new File(["x"], name, { type: "text/plain" });
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    // Sequenced, so the second list reconciles against the first rather
    // than mounting fresh -- which is where a duplicate key does damage.
    choose([txt("a.txt")]);
    choose([txt("notes.txt"), txt("notes.txt")]);

    const notice = screen.getByText(/files weren't added/i).closest(".warncard");
    expect(notice).toHaveTextContent("2 files weren't added");
    expect(within(notice).getAllByRole("listitem")).toHaveLength(2);
  });

  it("clears the previous refusals when the next selection succeeds", () => {
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

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
    seed([{ file: pdf("cd_biddrawings.pdf"), docType: "Drawings" }]);
    renderConfirm();

    fireEvent.change(screen.getByLabelText(/type for cd_biddrawings\.pdf/i), { target: { value: "Scope" } });

    expect(screen.getByText(/1 blocking/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /start takeoff/i })[0]).toBeDisabled();
    expect(screen.getByLabelText(/blocks processing/i)).toBeTruthy();
  });
});
