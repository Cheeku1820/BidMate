/* ============================================================
   ProcessingStatus.test.jsx — screen E over the queue (task-15).

   The screen is a view onto store.getProcessing: every sheet in the
   run with its stage word, the documents that couldn't be read, and a
   way into the review workspace the moment one sheet is complete. On
   mount with no run it starts one itself (store.startTakeoff) -- that
   is the flow from screen D, where "Start takeoff" already asked for
   the run; this screen is where the estimator lands either way, so it
   never asks a second time.

   Fake timers are scoped to the polling tests and put back after each
   test, so a leaked fake clock can't stall an unrelated findBy*. Under
   a fake clock those tests flush the first fetch with
   advanceTimersByTimeAsync(0) and assert with getBy* -- RTL's findBy*
   waits on the real clock and would hang (ConfirmDrawings.test.jsx
   does the same).
   ============================================================ */

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProcessingStatus from "./ProcessingStatus.jsx";

const renderScreen = (store) =>
  render(
    <MemoryRouter initialEntries={["/projects/p/processing"]}>
      <Routes>
        <Route path="/projects/:projectId/processing" element={<ProcessingStatus store={store} />} />
        <Route path="/projects/:projectId/takeoff" element={<p>review workspace</p>} />
        <Route path="/projects/:projectId/documents" element={<p>upload documents</p>} />
      </Routes>
    </MemoryRouter>,
  );

const poll = (over) => ({
  documents: [{ id: "d", filename: "E.pdf", docType: "Drawings", state: "read", reason: "", sheetCount: 2 }],
  run: {
    state: "running",
    reason: "",
    completeCount: 1,
    totalCount: 2,
    sheets: [
      { id: "s1", number: "E2.1", title: "Power plan", stage: "complete", reason: "", note: "", itemCount: 42 },
      { id: "s2", number: "E2.2", title: "Lighting plan", stage: "finding", reason: "", note: "", itemCount: 0 },
    ],
  },
  ...over,
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ProcessingStatus", () => {
  it("lists every sheet with its stage word and enables review at the first complete sheet", async () => {
    const store = { getProcessing: vi.fn().mockResolvedValue(poll()) };
    renderScreen(store);
    expect(await screen.findByText("Complete")).toBeInTheDocument();
    expect(screen.getByText("Finding electrical items")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue to review" })).toHaveAttribute("href", "/projects/p/takeoff");
    expect(screen.getByText("1 of 2 sheets complete")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reading your drawings" })).toBeInTheDocument();
    expect(
      screen.getByText("You can leave this page. Sheets keep processing and are reviewable as they finish."),
    ).toBeInTheDocument();
    // The count is a quantity, so it is tabular; the sheet is named as
    // number and title together.
    expect(screen.getByText("42")).toHaveClass("tabular");
    expect(screen.getByText("E2.1")).toBeInTheDocument();
    expect(screen.getByText("Power plan")).toBeInTheDocument();
  });

  it("does not offer review before any sheet is complete", async () => {
    const p = poll({
      run: {
        ...poll().run,
        state: "queued",
        completeCount: 0,
        sheets: poll().run.sheets.map((s) => ({ ...s, stage: "waiting", itemCount: 0 })),
      },
    });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue(p) });
    expect((await screen.findAllByText("Waiting")).length).toBe(2);
    expect(screen.queryByRole("link", { name: "Continue to review" })).not.toBeInTheDocument();
    expect(screen.getByText("0 of 2 sheets complete")).toBeInTheDocument();
  });

  it("polls every 3 seconds and stops when the run completes", async () => {
    vi.useFakeTimers();
    const getProcessing = vi
      .fn()
      .mockResolvedValueOnce(poll())
      .mockResolvedValue(poll({ run: { ...poll().run, state: "complete", completeCount: 2 } }));
    renderScreen({ getProcessing });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Finding electrical items")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Processing complete")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(6200));
    expect(getProcessing).toHaveBeenCalledTimes(2);
    // Finished: the way into review is offered in the body too.
    expect(screen.getAllByRole("link", { name: "Continue to review" }).length).toBeGreaterThan(1);
  });

  it("keeps the last state through a failed poll and tries again on the next tick", async () => {
    vi.useFakeTimers();
    const getProcessing = vi
      .fn()
      .mockResolvedValueOnce(poll())
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue(poll({ run: { ...poll().run, state: "complete", completeCount: 2 } }));
    renderScreen({ getProcessing });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Finding electrical items")).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Finding electrical items")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(3100));
    expect(screen.getByText("Processing complete")).toBeInTheDocument();
    expect(getProcessing).toHaveBeenCalledTimes(3);
  });

  it("stops polling when the screen unmounts", async () => {
    vi.useFakeTimers();
    const getProcessing = vi.fn().mockResolvedValue(poll());
    const { unmount } = renderScreen({ getProcessing });
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText("Finding electrical items")).toBeInTheDocument();
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(9500));
    expect(getProcessing).toHaveBeenCalledTimes(1);
  });

  it("shows a failed sheet's reason and a completed run with failures in words", async () => {
    const p = poll({
      run: {
        ...poll().run,
        state: "complete_with_failures",
        sheets: [
          {
            id: "s1",
            number: "E2.1",
            title: "Power plan",
            stage: "complete",
            reason: "",
            note: "Schedules weren't checked on this sheet.",
            itemCount: 42,
          },
          {
            id: "s2",
            number: "E2.2",
            title: "Lighting plan",
            stage: "attention",
            reason: "This sheet couldn't be processed. Start the takeoff again to retry it.",
            note: "",
            itemCount: 0,
          },
        ],
      },
    });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue(p) });
    expect(await screen.findByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText(/couldn't be processed/)).toBeInTheDocument();
    expect(screen.getByText("Schedules weren't checked on this sheet.")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Processing finished with 1 sheet needing attention" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Continue to review" }).length).toBeGreaterThan(0);
  });

  it("does not call a run complete when every sheet in it needs attention", async () => {
    // Seen live: a scanned set whose sheets were unreadable at read
    // time never gets sheet jobs, so the run reports "complete" with
    // every sheet at attention and none complete.
    const p = poll({
      run: {
        ...poll().run,
        state: "complete",
        completeCount: 0,
        totalCount: 3,
        sheets: ["Page 1", "Page 2", "Page 3"].map((n, i) => ({
          id: `s${i}`,
          number: n,
          title: "",
          stage: "attention",
          reason: "The sheet is a scanned image with no readable drawing content.",
          note: "",
          itemCount: 0,
        })),
      },
    });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue(p) });
    expect(
      await screen.findByRole("heading", { name: "Processing finished with 3 sheets needing attention" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Needs attention").length).toBe(3);
    expect(screen.getByText("0 of 3 sheets complete")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue to review" })).not.toBeInTheDocument();
  });

  it("lists a document that couldn't be read above the sheets, with its reason", async () => {
    const p = poll({
      documents: [
        ...poll().documents,
        { id: "d2", filename: "Specs.pdf", docType: "Drawings", state: "failed", reason: "This file is password protected.", sheetCount: 0 },
      ],
    });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue(p) });
    expect(await screen.findByText("Specs.pdf")).toBeInTheDocument();
    expect(screen.getByText("This file is password protected.")).toBeInTheDocument();
  });

  it("shows the run's own reason when it finished with failures before any sheet ran", async () => {
    const p = poll({
      run: {
        ...poll().run,
        state: "complete_with_failures",
        reason: "The drawings couldn't be classified. Start the takeoff again to retry.",
        completeCount: 0,
        sheets: poll().run.sheets.map((s) => ({ ...s, stage: "waiting", itemCount: 0 })),
      },
    });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue(p) });
    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't be classified/);
    expect(screen.getByRole("heading", { name: "Processing couldn't finish" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue to review" })).not.toBeInTheDocument();
  });

  it("with no run yet, starts one itself and says the page can be left", async () => {
    // Screen D's "Start takeoff" already asked for the run; landing
    // here with none going means the request is still the estimator's
    // intent, so the screen starts it rather than asking twice.
    const startTakeoff = vi.fn().mockResolvedValue({ runId: "r" });
    renderScreen({ getProcessing: vi.fn().mockResolvedValue({ ...poll(), run: null }), startTakeoff });
    expect(
      await screen.findByText("You can leave this page. Sheets keep processing and are reviewable as they finish."),
    ).toBeInTheDocument();
    expect(startTakeoff).toHaveBeenCalledWith("p");
    expect(screen.queryByRole("button", { name: "Start takeoff" })).not.toBeInTheDocument();
  });

  it("does not start a run when one is already going", async () => {
    const store = { getProcessing: vi.fn().mockResolvedValue(poll()), startTakeoff: vi.fn() };
    renderScreen(store);
    expect(await screen.findByText("Reading your drawings")).toBeInTheDocument();
    expect(store.startTakeoff).not.toHaveBeenCalled();
  });

  it("treats run_in_flight as success, not an error", async () => {
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ ...poll(), run: null }),
      startTakeoff: vi.fn().mockRejectedValue({ code: "run_in_flight", message: "A run is already in progress." }),
    };
    renderScreen(store);
    expect(await screen.findByText("Reading your drawings")).toBeInTheDocument();
    expect(screen.queryByText(/run is already in progress/i)).not.toBeInTheDocument();
  });

  it("shows the server's message and a way back to documents on no_readable_drawings, and does not poll", async () => {
    vi.useFakeTimers();
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ ...poll(), run: null }),
      startTakeoff: vi
        .fn()
        .mockRejectedValue({ code: "no_readable_drawings", message: "None of the uploaded documents could be read." }),
    };
    renderScreen(store);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText(/none of the uploaded documents could be read/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to documents/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /continue to review/i })).toBeNull();
    await act(() => vi.advanceTimersByTimeAsync(9500));
    expect(store.getProcessing).toHaveBeenCalledTimes(1);
  });

  it("shows the server's message and a way back when a set is still being read, and does not poll", async () => {
    vi.useFakeTimers();
    const store = {
      getProcessing: vi.fn().mockResolvedValue({ ...poll(), run: null }),
      startTakeoff: vi
        .fn()
        .mockRejectedValue({ code: "drawings_still_reading", message: "A drawing set is still being read. Wait for it to finish before starting the takeoff." }),
    };
    renderScreen(store);
    await act(() => vi.advanceTimersByTimeAsync(0));
    expect(screen.getByText(/a drawing set is still being read/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to documents/i })).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(9500));
    expect(store.getProcessing).toHaveBeenCalledTimes(1);
  });

  it("surfaces a failure to load processing status as an error, with a way back to documents", async () => {
    const store = { getProcessing: vi.fn().mockRejectedValue({}), startTakeoff: vi.fn() };
    renderScreen(store);
    expect(await screen.findByText(/couldn't load this project's processing status/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to documents/i })).toBeInTheDocument();
    await waitFor(() => expect(store.startTakeoff).not.toHaveBeenCalled());
  });
});
