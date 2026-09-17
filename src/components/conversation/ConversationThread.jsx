/* ============================================================
   ConversationThread.jsx — the messages, oldest first.

   Autoscroll only while the reader is already at the bottom: an
   estimator who scrolled up to reread an earlier answer must not be
   yanked down by a streaming one. Errors live in the bubble they
   belong to, never in a toast.

   One status region, outside the list, says "Waiting for an answer"
   and "Answer complete". The list itself is not live: a streaming
   answer re-announced on every delta is noise, and a live region
   nested inside another double-speaks.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import AnswerText from "./AnswerText.jsx";

export default function ConversationThread({ messages, pending, onRetry }) {
  const listRef = useRef(null);
  const stickToBottom = useRef(true);
  const wasStreaming = useRef(false);
  const [announce, setAnnounce] = useState("");

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  };

  useEffect(() => {
    const el = listRef.current;
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight;
  });

  useEffect(() => {
    const streaming = pending?.state === "streaming";
    if (streaming) setAnnounce(pending.text ? "" : "Waiting for an answer");
    else if (wasStreaming.current && pending === null) setAnnounce("Answer complete");
    else setAnnounce("");
    wasStreaming.current = streaming;
  }, [pending]);

  return (
    <>
      <p className="sr-only" role="status">{announce}</p>
      {/* list-style: none drops the list semantics in VoiceOver; the
          explicit role keeps them. */}
      <ol ref={listRef} className="conversation__thread" onScroll={onScroll} role="list">
        {messages.map((m) => (
          <li key={m.id} className={`conversation__turn conversation__turn--${m.role}`}>
            {m.role === "answer" ? <AnswerText text={m.text} /> : <p>{m.text}</p>}
          </li>
        ))}
        {pending && (
          <li className="conversation__turn conversation__turn--answer" aria-busy={pending.state === "streaming"}>
            {pending.text ? <AnswerText text={pending.text} /> : pending.state === "streaming" && (
              <span className="conversation__waiting" aria-hidden="true">
                <span /><span /><span />
              </span>
            )}
            {pending.state === "error" && (
              <p className="conversation__error">
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
    </>
  );
}
