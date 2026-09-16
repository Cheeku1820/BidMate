/* ============================================================
   ProcessingStatus.test.jsx — screen E as a minimal stub (task-12).

   The engine now runs behind the API: this screen asks
   store.getProcessing what's already going and starts a run
   (store.startTakeoff) if nothing is. Tasks 13-15 replace this with
   the real per-sheet progress view; these tests pin only the stub
   contract described in task-12-brief.md.
   ============================================================ */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProcessingStatus from "./ProcessingStatus.jsx";

const renderProcessing = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/processing"]}>
      <Routes>
        <Route path="/projects/:projectId/processing" element={<ProcessingStatus store={store} />} />
        <Route path="/projects/:projectId/takeoff" element={<p>review workspace</p>} />
        <Route path="/projects/:projectId/documents" element={<p>upload documents</p>} />
      </Routes>
    </MemoryRouter>,
  );

describe("ProcessingStatus", () => {
  it("starts a run when none is going, then shows the reading state with a link to the takeoff", async () => {
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ documents: [{ id: "d1" }], run: null }),
      startTakeoff: vi.fn().mockResolvedValue({ runId: "r1" }),
    };
    renderProcessing(store);

    await waitFor(() => expect(store.startTakeoff).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("Reading your drawings")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /continue to review/i }).length).toBeGreaterThan(0);
  });

  it("does not start a run when one is already going", async () => {
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ documents: [{ id: "d1" }], run: { state: "running", sheets: [] } }),
      startTakeoff: vi.fn(),
    };
    renderProcessing(store);

    expect(await screen.findByText("Reading your drawings")).toBeInTheDocument();
    expect(store.startTakeoff).not.toHaveBeenCalled();
  });

  it("treats run_in_flight as success, not an error", async () => {
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ documents: [{ id: "d1" }], run: null }),
      startTakeoff: vi.fn().mockRejectedValue({ code: "run_in_flight", message: "A run is already in progress." }),
    };
    renderProcessing(store);

    expect(await screen.findByText("Reading your drawings")).toBeInTheDocument();
    expect(screen.queryByText(/run is already in progress/i)).not.toBeInTheDocument();
  });

  it("shows the server's message and a way back to documents on no_readable_drawings", async () => {
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ documents: [{ id: "d1" }], run: null }),
      startTakeoff: vi.fn().mockRejectedValue({ code: "no_readable_drawings", message: "None of the uploaded documents could be read." }),
    };
    renderProcessing(store);

    expect(await screen.findByText(/none of the uploaded documents could be read/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to documents/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /continue to review/i })).toBeNull();
  });

  it("surfaces a failure to load processing status as an error, with a way back to documents", async () => {
    const store = {
      getProcessing: vi.fn().mockRejectedValue({}),
      startTakeoff: vi.fn(),
    };
    renderProcessing(store);

    expect(await screen.findByText(/couldn't load this project's processing status/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to documents/i })).toBeInTheDocument();
  });
});
