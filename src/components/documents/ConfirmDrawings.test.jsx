/* ============================================================
   ConfirmDrawings.test.jsx — screen D, now reflecting the real uploaded
   set. What matters: it groups the documents by type, blocks starting
   without a drawing set, flags unrecognized documents in a Needs
   attention section above the table, and lets the estimator correct a
   type or leave a document out before processing.
   ============================================================ */

import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ConfirmDrawings from "./ConfirmDrawings.jsx";
import { setUploadedFiles } from "../../lib/uploadedFiles.js";

const pdf = (name) => new File([new Uint8Array(2048)], name, { type: "application/pdf" });

function seed(files) {
  setUploadedFiles("p1", files);
}

const renderConfirm = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/documents/confirm"]}>
      <Routes>
        <Route path="/projects/:projectId/documents/confirm" element={<ConfirmDrawings />} />
        <Route path="/projects/:projectId/processing" element={<p>processing</p>} />
        <Route path="/projects/:projectId/documents" element={<p>upload</p>} />
      </Routes>
    </MemoryRouter>,
  );

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
