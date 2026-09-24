import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConversationPanel from "./ConversationPanel.jsx";
import { ConversationScreenProvider, useConversationSelection, useConversationView } from "./screenContext.jsx";

function makeStore({ thread, messages, answer = ["Nothing ", "blocks export."], error = null } = {}) {
  return {
    listConversation: vi.fn().mockResolvedValue(messages ?? thread ?? []),
    sendMessage: vi.fn(async (_id, _body, onDelta) => {
      if (error) throw error;
      for (const chunk of answer) onDelta(chunk);
      return { id: "a1" };
    }),
    applyProposal: vi.fn().mockResolvedValue({}),
    setProposalStatus: vi.fn().mockResolvedValue({}),
  };
}

// The mapped (camelCase) shape mapPanelProposal produces
// (src/lib/store/api-mapping.js) -- the same shape ProposalCard.test.jsx's
// own `item()` fixture uses. The inner `proposal` field stays snake_case,
// the wire shape the assistant sent it in (applyProposal.js's own note).
const ITEM_PROPOSAL = {
  kind: "item",
  summary: "Name 6 items on E2.1 2x4 LED troffer, type F.",
  note: "Approving stays with you.",
  count: 6,
  sheetNumber: "E2.1",
  itemId: "i1",
  approve: false,
  proposal: { intent: "reclassify", target_item_ids: ["i1"], versions: { i1: 1 }, name: "2x4 LED troffer, type F" },
  targetsPreview: [{ label: "Unclassified symbol", detail: "6 EA" }],
  moreCount: 0,
};

async function ask(text) {
  const box = await screen.findByLabelText("Ask a question");
  await userEvent.type(box, `${text}{Enter}`);
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

  it("adds the sheet and the selection to the blueprint's context line", async () => {
    renderPanel({
      pathname: "/projects/p1/takeoff",
      selection: { sheetId: "s1", sheetLabel: "E2.1", itemId: "i1", itemLabel: "20A duplex receptacle" },
    });
    await waitFor(() => expect(screen.getByText("Blueprint · E2.1 · 20A duplex receptacle selected")).toBeTruthy());
  });

  it("names the selection and the filter, but no sheet, on the project-wide spreadsheet", async () => {
    renderPanel({
      pathname: "/projects/p1/spreadsheet",
      selection: { sheetId: "s1", sheetLabel: "E2.1", itemId: "i1", itemLabel: "20A duplex receptacle" },
      view: { filter: "attention", search: "" },
    });
    await waitFor(() => expect(screen.getByText("Spreadsheet · 20A duplex receptacle selected · filtered to Needs attention")).toBeTruthy());
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

  it("sends the composer's text on Enter, keeps focus but goes read-only while streaming, and sends the view", async () => {
    // Read-only rather than disabled: a disabled textarea drops focus to
    // <body>, where the blueprint's single-key shortcuts (a, r, e, j, k)
    // would fire on the estimator's next keystroke.
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
    expect(box.readOnly).toBe(true);
    expect(box.disabled).toBe(false);
    expect(document.activeElement).toBe(box);
    expect(screen.getByRole("button", { name: "Send" }).disabled).toBe(true);
    await userEvent.type(box, "again{Enter}");
    expect(store.sendMessage).toHaveBeenCalledTimes(1);
    await act(async () => release());
    await waitFor(() => expect(box.readOnly).toBe(false));
  });

  it("does not send on Enter while an input method is composing", async () => {
    const { store } = renderPanel();
    const box = await screen.findByLabelText("Ask a question");
    await userEvent.type(box, "受け");
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(store.sendMessage).not.toHaveBeenCalled();
    expect(box.value).toBe("受け");
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
    expect(box.readOnly).toBe(true);

    rerender(
      <ConversationScreenProvider panelOpen={true} setPanelOpen={onToggle}>
        <ConversationPanel store={store} projectId="p2" pathname="/projects/p2/export" open={true} onToggle={onToggle} />
      </ConversationScreenProvider>,
    );

    await waitFor(() => expect(screen.getByLabelText("Ask a question").readOnly).toBe(false));
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

  it("renders the stored thread oldest first, as a list", async () => {
    renderPanel({ store: makeStore({ thread: [
      { id: "m1", role: "estimator", text: "First?", screen: { name: "export" }, createdAt: "2026-09-16T10:00:00Z" },
      { id: "m2", role: "answer", text: "First answer.", screen: null, createdAt: "2026-09-16T10:00:05Z" },
    ] }) });
    const items = await screen.findAllByRole("listitem");
    expect(items[0].textContent).toContain("First?");
    expect(items[1].textContent).toContain("First answer.");
    // list-style: none drops the list semantics in VoiceOver; the explicit
    // role keeps them. The list itself is not a live region.
    const list = screen.getByRole("list");
    expect(list.getAttribute("role")).toBe("list");
    expect(list.getAttribute("aria-live")).toBeNull();
  });

  it("announces waiting and completion through one status region outside the list", async () => {
    let release;
    const store = makeStore();
    store.sendMessage = vi.fn((_id, _body, onDelta) => new Promise((resolve) => {
      release = () => { onDelta("Done."); resolve({ id: "a1" }); };
    }));
    renderPanel({ store });
    const example = await screen.findByRole("button", { name: "What's still blocking export?" });
    const status = screen.getByRole("status");
    expect(status.textContent).toBe("");
    await userEvent.click(example);
    expect(status.textContent).toBe("Waiting for an answer");
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.queryByLabelText("Waiting for an answer")).toBeNull();
    await act(async () => release());
    await waitFor(() => expect(status.textContent).toBe("Answer complete"));
    expect(screen.getByRole("list").contains(status)).toBe(false);
  });

  it("keeps an error's text in its bubble without a second status region", async () => {
    renderPanel({ store: makeStore({ error: { code: "busy", message: "Busy right now — ask again in a moment" } }) });
    await userEvent.click(await screen.findByRole("button", { name: "What's still blocking export?" }));
    const error = await screen.findByText(/Busy right now/);
    expect(error.getAttribute("role")).toBeNull();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toBe("");
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

  it("never shows a browser's own error text, only the recovery copy", async () => {
    const store = makeStore();
    store.sendMessage = vi.fn(async () => { throw new TypeError("Failed to fetch"); });
    renderPanel({ store });
    await userEvent.click(await screen.findByRole("button", { name: "What's still blocking export?" }));
    await screen.findByText("Answer interrupted — ask again");
    expect(screen.queryByText("Failed to fetch")).toBeNull();
  });

  it("renders as a strip with an open control when closed", async () => {
    const { onToggle } = renderPanel({ open: false });
    expect(screen.queryByLabelText("Ask a question")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Open the conversation panel" }));
    expect(onToggle).toHaveBeenCalled();
  });

  it("renders the card that came with an answer and applies it through the record's endpoint", async () => {
    const store = makeStore({ messages: [] });
    store.sendMessage = vi.fn(async (id, body, onDelta) => {
      onDelta("Six items read as type F.");
      return { id: "m1", proposal: ITEM_PROPOSAL };
    });
    store.applyProposal = vi.fn().mockResolvedValue({});
    store.setProposalStatus = vi.fn().mockResolvedValue({});
    renderPanel({ store });
    await ask("these are all type F");
    expect(await screen.findByText(ITEM_PROPOSAL.summary)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));
    // The brief's table describes store.applyProposal as a 2-arg call;
    // the real store (src/lib/store/api.js:341) takes three positional
    // arguments -- (itemId, proposal, { approve, note }) -- and
    // ProposalCard.test.jsx already documents the same deviation for the
    // same reason: this follows the real signature, not the table.
    expect(store.applyProposal).toHaveBeenCalledWith(
      "i1",
      expect.objectContaining({ name: ITEM_PROPOSAL.proposal.name }),
      { approve: false, note: "" },
    );
    expect(store.setProposalStatus).toHaveBeenCalledWith("p1", "m1", "applied");
    expect(await screen.findByText("Applied")).toBeInTheDocument();
  });

  it("renders stored cards with their statuses on reload", async () => {
    const store = makeStore({ messages: [
      { id: "q1", role: "estimator", text: "these are all type F", screen: null, createdAt: "2026-09-24T10:00:00Z" },
      { id: "m1", role: "answer", text: "Six items.", screen: null, createdAt: "2026-09-24T10:00:01Z",
        proposal: ITEM_PROPOSAL, proposalStatus: "applied" },
    ] });
    renderPanel({ store });
    expect(await screen.findByText("Applied")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("dismiss records the outcome and writes nothing else", async () => {
    const store = makeStore({ messages: [
      { id: "m1", role: "answer", text: "Six items.", screen: null, createdAt: "2026-09-24T10:00:01Z",
        proposal: ITEM_PROPOSAL, proposalStatus: "offered" },
    ] });
    store.setProposalStatus = vi.fn().mockResolvedValue({});
    store.applyProposal = vi.fn();
    renderPanel({ store });
    await userEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
    expect(store.setProposalStatus).toHaveBeenCalledWith("p1", "m1", "dismissed");
    expect(store.applyProposal).not.toHaveBeenCalled();
  });

  it("a refused apply leaves the card offered with the server's words", async () => {
    const store = makeStore({ messages: [
      { id: "m1", role: "answer", text: "Six items.", screen: null, createdAt: "2026-09-24T10:00:01Z",
        proposal: ITEM_PROPOSAL, proposalStatus: "offered" },
    ] });
    store.applyProposal = vi.fn().mockRejectedValue({ code: "item_missing_info", message: "This item is missing required information." });
    store.setProposalStatus = vi.fn();
    renderPanel({ store });
    await userEvent.click(await screen.findByRole("button", { name: "Apply" }));
    expect(await screen.findByText("This item is missing required information.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(store.setProposalStatus).not.toHaveBeenCalled();
  });
});
