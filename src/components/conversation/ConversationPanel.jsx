/* ============================================================
   ConversationPanel.jsx — the right-hand column on every project
   screen (docs/specs/conversation-panel.md).

   Read-only in this slice: it answers about what is in view and says
   where in the product a change is made. It is titled and written as a
   colleague, per CLAUDE.md -- never an assistant.

   Owns the thread state (loaded once per project, appended locally),
   the in-flight answer, and the composer. Open/closed is the shell's,
   so the same value can be handed to the screen context and Workspace
   can react to it.
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, PanelRightClose, Send } from "lucide-react";
import ConversationThread from "./ConversationThread.jsx";
import { exampleQuestions } from "./exampleQuestions.js";
import { SCREEN_LABELS, screenNameFromPath, useConversationScreenContext } from "./screenContext.jsx";
import { STATUS } from "../../lib/vocabulary.js";

const NOT_CONFIGURED = "not_configured";

function contextLine(name, selection, view) {
  const parts = [SCREEN_LABELS[name] ?? "This project"];
  if (selection.sheetLabel) parts.push(selection.sheetLabel);
  if (selection.itemLabel) parts.push(`${selection.itemLabel} selected`);
  if (view.filter && STATUS[view.filter]) parts.push(`filtered to ${STATUS[view.filter].label}`);
  return parts.join(" · ");
}

function toWire(name, selection, view) {
  return {
    name,
    sheet_id: selection.sheetId ?? null,
    item_id: selection.itemId ?? null,
    view: view.filter || view.search ? { filter: view.filter ?? null, search: view.search || null } : null,
  };
}

export default function ConversationPanel({ store, projectId, pathname, open, onToggle }) {
  const { selection, view } = useConversationScreenContext();
  const name = screenNameFromPath(pathname);

  const [messages, setMessages] = useState(null);
  const [pending, setPending] = useState(null);
  const [draft, setDraft] = useState("");
  const [unavailable, setUnavailable] = useState(null);
  const lastQuestion = useRef(null);
  const lastLocalId = useRef(null);
  const abort = useRef(null);

  useEffect(() => {
    let alive = true;
    setMessages(null);
    setPending(null);
    setDraft("");
    setUnavailable(null);
    lastQuestion.current = null;
    lastLocalId.current = null;
    store.listConversation(projectId)
      .then((rows) => { if (alive) setMessages(rows); })
      .catch(() => { if (alive) setMessages([]); });
    return () => {
      alive = false;
      abort.current?.abort();
    };
  }, [store, projectId]);

  const send = useCallback(async (text) => {
    const question = text.trim();
    if (!question || messages === null || pending?.state === "streaming") return;
    const screen = toWire(name, selection, view);
    lastQuestion.current = { text: question, screen };
    const localId = `local-${Date.now()}`;
    lastLocalId.current = localId;
    setMessages((m) => [...(m ?? []), { id: localId, role: "estimator", text: question, screen }]);
    setPending({ state: "streaming", text: "" });
    setDraft("");
    abort.current = new AbortController();
    try {
      const { id } = await store.sendMessage(projectId, { text: question, screen }, (chunk) => {
        setPending((p) => ({ state: "streaming", text: (p?.text ?? "") + chunk }));
      }, abort.current.signal);
      setPending((p) => {
        setMessages((m) => [...(m ?? []), { id, role: "answer", text: p?.text ?? "", screen: null }]);
        return null;
      });
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (err?.code === NOT_CONFIGURED) {
        setUnavailable(err.message);
        setPending(null);
        return;
      }
      setPending((p) => ({ state: "error", text: p?.text ?? "", message: err?.message ?? "Answer interrupted — ask again", retry: err?.code === "busy" }));
    }
  }, [store, projectId, name, selection, view, pending, messages]);

  const retry = () => {
    const last = lastQuestion.current;
    if (!last) return;
    setMessages((m) => {
      const rows = m ?? [];
      const lastRow = rows[rows.length - 1];
      return lastRow?.id === lastLocalId.current ? rows.slice(0, -1) : rows;
    });
    send(last.text);
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(draft);
    }
  };

  if (!open) {
    return (
      <aside className="conversation conversation--closed" aria-label="Ask about this project">
        <button type="button" className="conversation__toggle" onClick={onToggle} aria-label="Open the conversation panel" title="Ask about this project">
          <MessageSquare size={18} />
        </button>
      </aside>
    );
  }

  const streaming = pending?.state === "streaming";
  const loading = messages === null;
  const examples = messages && messages.length === 0 && !pending ? exampleQuestions(name) : [];

  return (
    <aside className="conversation" aria-label="Ask about this project">
      <header className="conversation__head">
        <div>
          <h2 className="conversation__title">Ask about this project</h2>
          <p className="conversation__context">{contextLine(name, selection, view)}</p>
        </div>
        <button type="button" className="iconbtn" onClick={onToggle} aria-label="Close the conversation panel">
          <PanelRightClose size={18} />
        </button>
      </header>

      {messages === null ? (
        <p className="conversation__empty">Loading the conversation</p>
      ) : (
        <ConversationThread messages={messages} pending={pending} onRetry={retry} />
      )}

      {examples.length > 0 && !unavailable && (
        <div className="conversation__examples">
          {examples.map((q) => (
            <button key={q} type="button" className="conversation__example" onClick={() => send(q)}>{q}</button>
          ))}
        </div>
      )}

      {unavailable && <p className="conversation__unavailable" role="status">{unavailable}</p>}

      <form className="conversation__composer" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
        <label htmlFor="conversation-draft" className="conversation__label">Ask a question</label>
        <textarea
          id="conversation-draft"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          rows={2}
          maxLength={4000}
          disabled={streaming || loading || Boolean(unavailable)}
        />
        <button type="submit" className="btn btn--primary" disabled={streaming || loading || Boolean(unavailable) || !draft.trim()} aria-label="Send">
          <Send size={16} />
        </button>
      </form>
    </aside>
  );
}
