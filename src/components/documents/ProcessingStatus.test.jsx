/* ============================================================
   ProcessingStatus.test.jsx — screen E behaviour.

   Two rules carry the weight: on completion it stands the sample takeoff
   into the project (attachSampleTakeoff) exactly once and reveals a
   Continue action, and re-entering the screen for an already-sampled
   project does NOT re-run and overwrite review progress -- it detects the
   sample and shows the completed state straight away.
   ============================================================ */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProcessingStatus from "./ProcessingStatus.jsx";
import { setUploadedFiles, clearUploadedFiles } from "../../lib/uploadedFiles.js";
import * as engineClient from "../../lib/engineClient.js";

const renderProcessing = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p1/processing"]}>
      <Routes>
        <Route path="/projects/:projectId/processing" element={<ProcessingStatus store={store} />} />
        <Route path="/projects/:projectId/takeoff" element={<p>review workspace</p>} />
      </Routes>
    </MemoryRouter>,
  );

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

// Lets the mount effect's async project-lookup settle before advancing
// the simulated stage timers.
async function flushMicrotasks() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe("ProcessingStatus", () => {
  it("attaches the sample takeoff once when processing finishes, then offers Continue to review", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", sample: false }]),
      attachSampleTakeoff: vi.fn().mockResolvedValue(undefined),
    };
    renderProcessing(store);
    await flushMicrotasks();

    // Not done yet, no Continue action while sheets are still working.
    expect(screen.queryByRole("link", { name: /continue to review/i })).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(6000);
      await Promise.resolve();
    });

    expect(store.attachSampleTakeoff).toHaveBeenCalledTimes(1);
    expect(store.attachSampleTakeoff).toHaveBeenCalledWith("p1");
    expect(screen.getAllByRole("link", { name: /continue to review/i }).length).toBeGreaterThan(0);
  });

  it("does not re-process a project that already has a sample takeoff", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", sample: true }]),
      attachSampleTakeoff: vi.fn().mockResolvedValue(undefined),
    };
    renderProcessing(store);
    await flushMicrotasks();

    // Straight to complete, and crucially never re-attaches (which would
    // wipe the estimator's review progress).
    expect(screen.getAllByRole("link", { name: /continue to review/i }).length).toBeGreaterThan(0);

    await act(async () => {
      vi.advanceTimersByTime(6000);
      await Promise.resolve();
    });
    expect(store.attachSampleTakeoff).not.toHaveBeenCalled();
  });
});

describe("ProcessingStatus — replacing a takeoff that holds approvals", () => {
  // The engine path here is driven entirely by promise resolution (the
  // upload, the estimate call, the attach), not by the simulated per-sheet
  // timers the sample path uses. Real timers keep userEvent's own internal
  // delays out of the way instead of fighting the fake clock for a ticker
  // this flow never depends on.
  beforeEach(() => {
    vi.useRealTimers();
    setUploadedFiles("p1", [{ file: new File([new Uint8Array(1024)], "e1.1.pdf", { type: "application/pdf" }), docType: "Drawings" }]);
    vi.spyOn(engineClient, "estimateProject").mockResolvedValue({
      totals: { item_count: 4, total_direct_cost: 12000 },
      sheets: [{ id: "e11" }],
      location: "",
      source: "engine",
    });
  });

  afterEach(() => {
    clearUploadedFiles("p1");
    vi.restoreAllMocks();
  });

  it("asks before replacing a takeoff that holds approvals", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", name: "Riverside" }]),
      attachEngineTakeoff: vi
        .fn()
        .mockRejectedValueOnce({
          code: "approved_items_present",
          message: "3 item(s) on this project are estimator approved.",
        })
        .mockResolvedValueOnce({ sheets: 1, items: 4 }),
    };
    renderProcessing(store);

    // The estimator sees what would be lost, in the server's own words.
    expect(await screen.findByText(/3 item\(s\) on this project are estimator approved/)).toBeInTheDocument();
    expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(1);

    await userEvent.click(screen.getByRole("button", { name: /replace the takeoff/i }));

    await waitFor(() => expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(2));
    expect(store.attachEngineTakeoff.mock.calls[1][2]).toEqual({ confirmReplace: true });
  });

  it("leaves the takeoff alone when the estimator declines", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", name: "Riverside" }]),
      attachEngineTakeoff: vi.fn().mockRejectedValue({
        code: "approved_items_present",
        message: "3 item(s) on this project are estimator approved.",
      }),
    };
    renderProcessing(store);

    await userEvent.click(await screen.findByRole("button", { name: /keep the current takeoff/i }));

    expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /replace the takeoff/i })).not.toBeInTheDocument();
  });
});
