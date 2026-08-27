/* ============================================================
   ProcessingStatus.test.jsx — screen E behaviour.

   With the seed/sample takeoff path removed, a project with no uploaded
   documents and no existing takeoff has nothing to process -- that is an
   error state, not a fallback. Re-entering a project that already has a
   takeoff goes straight to complete and never re-runs the engine.
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
  it("shows an error, not a fallback, when no documents were uploaded and no takeoff exists yet", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", itemsTotal: 0 }]),
    };
    renderProcessing(store);
    await flushMicrotasks();

    expect(
      screen.getByText(/no documents have been uploaded for this project yet\. upload a drawing set to start a takeoff\./i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /continue to review/i })).toBeNull();
  });

  it("does not re-process a project that already has a takeoff", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", itemsTotal: 12 }]),
    };
    renderProcessing(store);
    await flushMicrotasks();

    // Straight to complete -- no engine call, no error, and crucially no
    // re-run that would wipe the estimator's review progress.
    expect(screen.getAllByRole("link", { name: /continue to review/i }).length).toBeGreaterThan(0);
  });

  it("proceeds to processing an upload for a project with itemsTotal 0, rather than treating it as already done", async () => {
    // itemsTotal is the real signal mapProject emits (api-mapping.js); a
    // freshly created project starts at 0. The re-run guard must not read
    // that as "already has a takeoff" when there is an upload waiting --
    // it must call the engine, not take the early "done" return.
    vi.useRealTimers();
    setUploadedFiles("p2", [{ file: new File([new Uint8Array(1024)], "e1.1.pdf", { type: "application/pdf" }), docType: "Drawings" }]);
    vi.spyOn(engineClient, "estimateProject").mockResolvedValue({
      totals: { item_count: 4, total_direct_cost: 12000 },
      sheets: [{ id: "e11" }],
      location: "",
      source: "engine",
    });
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p2", itemsTotal: 0 }]),
      attachEngineTakeoff: vi.fn().mockResolvedValue(undefined),
    };

    render(
      <MemoryRouter initialEntries={["/projects/p2/processing"]}>
        <Routes>
          <Route path="/projects/:projectId/processing" element={<ProcessingStatus store={store} />} />
          <Route path="/projects/:projectId/takeoff" element={<p>review workspace</p>} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(engineClient.estimateProject).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/no documents have been uploaded/i)).not.toBeInTheDocument();

    clearUploadedFiles("p2");
    vi.restoreAllMocks();
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

  it("surfaces a failure that happens after the estimator confirms", async () => {
    const store = {
      listProjects: vi.fn().mockResolvedValue([{ id: "p1", name: "Riverside" }]),
      attachEngineTakeoff: vi
        .fn()
        .mockRejectedValueOnce({
          code: "approved_items_present",
          message: "3 item(s) on this project are estimator approved.",
        })
        .mockRejectedValueOnce({
          code: "request_failed",
          message: "The request failed (status 500). Try again.",
        }),
    };
    renderProcessing(store);

    await userEvent.click(await screen.findByRole("button", { name: /replace the takeoff/i }));

    // A second failure lands in the same error state as any other
    // processing failure -- not an unhandled rejection stranding the
    // estimator on a dialog that looks like it did nothing.
    expect(await screen.findByText(/the request failed \(status 500\)/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /replace the takeoff/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(store.attachEngineTakeoff).toHaveBeenCalledTimes(2);
  });
});
