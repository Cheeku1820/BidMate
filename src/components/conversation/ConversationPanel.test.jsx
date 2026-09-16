import { describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConversationPanel from "./ConversationPanel.jsx";
import { ConversationScreenProvider, useConversationSelection, useConversationView } from "./screenContext.jsx";

function makeStore({ thread = [], answer = ["Nothing ", "blocks export."], error = null } = {}) {
  return {
    listConversation: vi.fn().mockResolvedValue(thread),
    sendMessage: vi.fn(async (_id, _body, onDelta) => {
      if (error) throw error;
      for (const chunk of answer) onDelta(chunk);
      return { id: "a1" };
    }),
  };
}

function Reporter({ selection, view }) {
  if (selection) useConversationSelection(selection);
  if (view) useConversationView(view);
  return null;
}

const renderPanel = ({ store = makeStore(), pathname = "/projects/p1/export", open = true, selection, view } = {}) => {
  const onToggle = vi.fn();
  const utils = render(
    <ConversationScreenProvider panelOpen={open} setPanelOpen={onToggle}>
      {(selection || view) && <Reporter selection={selection} view={view} />}
      <ConversationPanel store={store} projectId="p1" pathname={pathname} open={open} onToggle={onToggle} />
    </ConversationScreenProvider>,
  );
  return { ...utils, store, onToggle };
};

describe("ConversationPanel", () => {
  it("is a labelled complementary region that names the screen in view", async () => {
    renderPanel({ pathname: "/projects/p1/documents/confirm" });
    const aside = screen.getByRole("complementary", { name: /ask about this project/i });
    expect(aside).toBeTruthy();
    await waitFor(() => expect(screen.getByText("Confirm drawings")).toBeTruthy());
  });

  it("adds the selection and the filter to the context line", async () => {
    renderPanel({
      pathname: "/projects/p1/spreadsheet",
      selection: { sheetId: "s1", sheetLabel: "E2.1", itemId: "i1", itemLabel: "20A duplex receptacle" },
      view: { filter: "attention", search: "" },
    });
    await waitFor(() => expect(screen.getByText("Spreadsheet · E2.1 · 20A duplex receptacle selected · filtered to Needs attention")).toBeTruthy());
  });

  it("shows three example questions when the thread is empty, and sends one on click", async () => {
    const { store } = renderPanel();
    const example = await screen.findByRole("button", { name: "What's still blocking export?" });
    expect(screen.getAllByRole("button", { name: /\?$/ })).toHaveLength(3);
    await userEvent.click(example);
    await waitFor(() => expect(store.sendMessage).toHaveBeenCalled());
    expect(store.sendMessage.mock.calls[0][1]).toEqual({
      text: "What's still blocking export?",
      screen: { name: "export", sheet_id: null, item_id: null, view: null },
    });
    await screen.findByText("Nothing blocks export.");
    expect(screen.queryByRole("button", { name: /\?$/ })).toBeNull();
  });

  it("sends the composer's text on Enter, disables it while streaming, and sends the view", async () => {
    let release;
    const store = makeStore();
    store.sendMessage = vi.fn((_id, _body, onDelta) => new Promise((resolve) => {
      onDelta("Partial");
      release = () => resolve({ id: "a1" });
    }));
    renderPanel({ store, pathname: "/projects/p1/spreadsheet", view: { filter: "missing", search: "LP-2" } });
    const box = await screen.findByLabelText("Ask a question");
    await userEvent.type(box, "What's missing?{Enter}");
    expect(store.sendMessage.mock.calls[0][1].screen).toEqual({ name: "spreadsheet", sheet_id: null, item_id: null, view: { filter: "missing", search: "LP-2" } });
    expect(screen.getByText("What's missing?")).toBeTruthy();
    expect(screen.getByText("Partial")).toBeTruthy();
    expect(box.disabled).toBe(true);
    await act(async () => release());
    await waitFor(() => expect(box.disabled).toBe(false));
  });

  it("resets pending, draft, and unavailable when the project changes mid-stream", async () => {
    const store = {
      listConversation: vi.fn().mockResolvedValue([]),
      sendMessage: vi.fn((_id, _body, onDelta, signal) => new Promise((_resolve, reject) => {
        onDelta("Partial");
        signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      })),
    };
    const onToggle = vi.fn();
    const { rerender } = render(
      <ConversationScreenProvider panelOpen={true} setPanelOpen={onToggle}>
        <ConversationPanel store={store} projectId="p1" pathname="/projects/p1/export" open={true} onToggle={onToggle} />
      </ConversationScreenProvider>,
    );
    const box = await screen.findByLabelText("Ask a question");
    await userEvent.type(box, "What's missing?{Enter}");
    await screen.findByText("Partial");
    expect(box.disabled).toBe(true);

    rerender(
      <ConversationScreenProvider panelOpen={true} setPanelOpen={onToggle}>
        <ConversationPanel store={store} projectId="p2" pathname="/projects/p2/export" open={true} onToggle={onToggle} />
      </ConversationScreenProvider>,
    );

    await waitFor(() => expect(screen.getByLabelText("Ask a question").disabled).toBe(false));
    expect(screen.queryByText("Partial")).toBeNull();
    expect(screen.getByLabelText("Ask a question").value).toBe("");
  });

  it("disables the composer while the conversation is loading", async () => {
    const store = {
      listConversation: vi.fn(() => new Promise(() => {})),
      sendMessage: vi.fn(),
    };
    renderPanel({ store });
    const box = await screen.findByLabelText("Ask a question");
    expect(box.disabled).toBe(true);
  });

  it("keeps a newline on Shift+Enter without sending", async () => {
    const { store } = renderPanel();
    const box = await screen.findByLabelText("Ask a question");
    await userEvent.type(box, "line one{Shift>}{Enter}{/Shift}line two");
    expect(store.sendMessage).not.toHaveBeenCalled();
    expect(box.value).toBe("line one\nline two");
  });

  it("renders the stored thread oldest first", async () => {
    renderPanel({ store: makeStore({ thread: [
      { id: "m1", role: "estimator", text: "First?", screen: { name: "export" }, createdAt: "2026-09-16T10:00:00Z" },
      { id: "m2", role: "answer", text: "First answer.", screen: null, createdAt: "2026-09-16T10:00:05Z" },
    ] }) });
    const items = await screen.findAllByRole("listitem");
    expect(items[0].textContent).toContain("First?");
    expect(items[1].textContent).toContain("First answer.");
  });

  it("says when the server is not set up and disables the composer", async () => {
    renderPanel({ store: makeStore({ error: { code: "not_configured", message: "The conversation panel isn't set up on this server" } }) });
    await userEvent.click(await screen.findByRole("button", { name: "What's still blocking export?" }));
    await screen.findByText("The conversation panel isn't set up on this server");
    expect(screen.getByLabelText("Ask a question").disabled).toBe(true);
  });

  it("offers a retry when busy", async () => {
    const { store } = renderPanel({ store: makeStore({ error: { code: "busy", message: "Busy right now — ask again in a moment" } }) });
    await userEvent.click(await screen.findByRole("button", { name: "What's still blocking export?" }));
    await screen.findByText("Busy right now — ask again in a moment");
    store.sendMessage.mockImplementation(async (_id, _body, onDelta) => { onDelta("Fine now."); return { id: "a2" }; });
    await userEvent.click(screen.getByRole("button", { name: "Ask again" }));
    await screen.findByText("Fine now.");
  });

  it("keeps the partial text and marks it interrupted", async () => {
    const store = makeStore();
    store.sendMessage = vi.fn(async (_id, _body, onDelta) => { onDelta("Half an "); throw { code: "interrupted", message: "Answer interrupted — ask again" }; });
    renderPanel({ store });
    await userEvent.click(await screen.findByRole("button", { name: "What's still blocking export?" }));
    await screen.findByText("Answer interrupted — ask again");
    expect(screen.getByText("Half an")).toBeTruthy();
  });

  it("renders as a strip with an open control when closed", async () => {
    const { onToggle } = renderPanel({ open: false });
    expect(screen.queryByLabelText("Ask a question")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open the conversation panel" }));
    expect(onToggle).toHaveBeenCalled();
  });
});
