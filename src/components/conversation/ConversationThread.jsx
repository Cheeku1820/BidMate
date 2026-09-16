/* ============================================================
   ConversationThread.jsx — the messages, oldest first.

   Autoscroll only while the reader is already at the bottom: an
   estimator who scrolled up to reread an earlier answer must not be
   yanked down by a streaming one. Errors live in the bubble they
   belong to, never in a toast.
   ============================================================ */

import { useEffect, useRef } from "react";
import AnswerText from "./AnswerText.jsx";

export default function ConversationThread({ messages, pending, onRetry }) {
  const listRef = useRef(null);
  const stickToBottom = useRef(true);

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  });

  return (
    <ol ref={listRef} className="conversation__thread" onScroll={onScroll} aria-live="polite">
      {messages.map((m) => (
        <li key={m.id} className={`conversation__turn conversation__turn--${m.role}`}>
          {m.role === "answer" ? <AnswerText text={m.text} /> : <p>{m.text}</p>}
        </li>
      ))}
      {pending && (
        <li className="conversation__turn conversation__turn--answer" aria-busy={pending.state === "streaming"}>
          {pending.text ? <AnswerText text={pending.text} /> : pending.state === "streaming" && (
            <span className="conversation__waiting" aria-label="Waiting for an answer">
              <span /><span /><span />
            </span>
          )}
          {pending.state === "error" && (
            <p className="conversation__error" role="status">
              {pending.message}
              {pending.retry && (
                <>
                  {" "}
                  <button type="button" className="linkbtn" onClick={onRetry}>Ask again</button>
                </>
              )}
            </p>
          )}
        </li>
      )}
    </ol>
  );
}
