/* ============================================================
   ProcessingStatus.test.jsx — screen E behaviour.

   Two rules carry the weight: on completion it stands the sample takeoff
   into the project (attachSampleTakeoff) exactly once and reveals a
   Continue action, and re-entering the screen for an already-sampled
   project does NOT re-run and overwrite review progress -- it detects the
   sample and shows the completed state straight away.
   ============================================================ */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProcessingStatus from "./ProcessingStatus.jsx";

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
