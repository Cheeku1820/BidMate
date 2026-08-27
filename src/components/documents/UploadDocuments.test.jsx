/* ============================================================
   UploadDocuments.test.jsx — screen C intake behaviour.

   The spec §10 states are what matter here: a clean PDF settles to
   "Uploaded" and enables starting a takeoff; a non-PDF, a duplicate, and
   a password-protected file each surface their own plain-language state
   and never count toward starting. Start is gated on at least one
   uploaded file.
   ============================================================ */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import UploadDocuments from "./UploadDocuments.jsx";

const pdf = (name, size = 1024) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

const renderUpload = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/documents"]}>
      <Routes>
        <Route path="/projects/:projectId/documents" element={<UploadDocuments />} />
        <Route path="/projects/:projectId/processing" element={<p>processing screen</p>} />
      </Routes>
    </MemoryRouter>,
  );

const fileInput = () => document.querySelector('input[type="file"]');

// Fires a change on the hidden file input with the given files. Using the
// input directly rather than userEvent.upload so fake timers don't have
// to interleave with user-event's async plumbing. Wrapped in act() so the
// React state update flushes before the next assertion.
function drop(files) {
  const input = fileInput();
  Object.defineProperty(input, "files", { value: files, configurable: true });
  act(() => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

const advance = (ms) => act(() => vi.advanceTimersByTime(ms));

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("UploadDocuments", () => {
  it("settles a clean PDF to Uploaded and only then enables Start takeoff", () => {
    renderUpload();
    const start = screen.getAllByRole("button", { name: /review detected drawings/i })[0];
    expect(start).toBeDisabled();

    drop([pdf("E-sheets.pdf")]);
    expect(screen.getByText(/uploading/i)).toBeTruthy();
    expect(start).toBeDisabled();

    advance(800);
    expect(screen.getByText(/^uploaded$/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /review detected drawings/i })[0]).toBeEnabled();
  });

  it("flags a non-PDF as unsupported and never counts it toward starting", () => {
    renderUpload();
    drop([new File(["x"], "notes.txt", { type: "text/plain" })]);
    advance(800);
    expect(screen.getByText(/not a pdf/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /review detected drawings/i })[0]).toBeDisabled();
  });

  it("flags a second identical file as a duplicate", () => {
    renderUpload();
    drop([pdf("set.pdf", 2048)]);
    advance(800);
    drop([pdf("set.pdf", 2048)]);
    expect(screen.getByText(/already added/i)).toBeTruthy();
  });

  it("flags a password-protected file and asks for an unlocked copy", () => {
    renderUpload();
    drop([pdf("E1-protected.pdf")]);
    advance(800);
    expect(screen.getByText(/password protected/i)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /review detected drawings/i })[0]).toBeDisabled();
  });

  it("auto-detects the type from the filename and shows a Detected hint", () => {
    renderUpload();
    drop([pdf("specs_part_1.pdf")]);
    advance(800);
    expect(screen.getByLabelText(/document type for specs_part_1\.pdf/i)).toHaveValue("Specifications");
    expect(screen.getByText("Detected")).toBeTruthy(); // the chip, not the intro copy
  });

  it("blocks continuing until at least one file is typed Drawings", () => {
    renderUpload();
    drop([pdf("specs_part_1.pdf")]); // detects as Specifications, not Drawings
    advance(800);

    // Uploaded, but nothing is a drawing set yet.
    expect(screen.getAllByRole("button", { name: /review detected drawings/i })[0]).toBeDisabled();
    expect(screen.getByText(/no drawing set yet/i)).toBeTruthy();

    // Correcting one to Drawings unblocks it.
    fireEvent.change(screen.getByLabelText(/document type for specs_part_1\.pdf/i), {
      target: { value: "Drawings" },
    });
    expect(screen.getAllByRole("button", { name: /review detected drawings/i })[0]).toBeEnabled();
  });

  it("removes a file from the list", () => {
    renderUpload();
    drop([pdf("remove-me.pdf")]);
    advance(800);
    const row = screen.getByText("remove-me.pdf").closest("tr");
    const removeBtn = within(row).getByRole("button", { name: /remove remove-me\.pdf/i });
    act(() => removeBtn.click());
    expect(screen.queryByText("remove-me.pdf")).toBeNull();
  });
});
