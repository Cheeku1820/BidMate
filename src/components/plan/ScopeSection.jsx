/* ============================================================
   ScopeSection.jsx — what the documents say the electrical work is,
   settled by a person before the takeoff runs. Lives on the project
   plan (docs/specs/project-plan-screen.md); it used to sit on Confirm
   drawings.

   The worker reads every uploaded file and lifts out scope statements:
   included, excluded, by others, or an alternate, each quoted verbatim
   from its source page. Nothing here is a takeoff item. A statement's
   status -- found, confirmed, dismissed -- is its own vocabulary, the
   same separation notes keep (CLAUDE.md: "a note's status is not an
   item's status"), drawn by PlanLine with .note-status, never Pill.jsx.

   Two ways to mount it. Self-fetching -- `store` + `projectId` -- loads
   the statements itself. Controlled -- `statements` + `onDecided` --
   renders what the plan screen already holds (the plan GET carries the
   scope array), so Scope and Exclusions on that screen are two views
   of one list and a decision in either updates both. Both modes write
   through store.decideScope: there is one write path per record.
   ============================================================ */

import { useEffect, useRef, useState } from "react";
import PlanLine from "./PlanLine.jsx";

export const KIND_ORDER = ["included", "excluded", "by_others", "alternate"];
export const KIND_LABELS = { included: "Included", excluded: "Excluded", by_others: "By others", alternate: "Alternates" };

function plural(n, word) {
  return `${n} ${n === 1 ? word : `${word}s`}`;
}

export default function ScopeSection({
  store,
  projectId,
  statements: controlled = null,
  onDecided = null,
  kinds = KIND_ORDER,
  title = "Scope stated in the documents",
  description = "What the documents say the electrical work includes and leaves out, quoted from the page it came from. Confirm each one, correct its wording, or dismiss it.",
  headingId = "scope-heading",
  emptyText = "No scope statements were found in the documents.",
}) {
  const isControlled = controlled !== null;
  const [fetched, setFetched] = useState(null);
  const [state, setState] = useState(isControlled ? "loaded" : "loading");

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (isControlled) return;
    setState("loading");
    store
      .listScope(projectId)
      .then((rows) => {
        if (!aliveRef.current) return;
        setFetched(rows);
        setState("loaded");
      })
      .catch(() => {
        if (!aliveRef.current) return;
        setState("failed");
      });
  }, [store, projectId, isControlled]);

  const all = isControlled ? controlled : fetched;
  const statements = (all ?? []).filter((s) => kinds.includes(s.kind));

  const decide = (id, change) =>
    store.decideScope(id, change).then((updated) => {
      if (!aliveRef.current) return updated;
      if (isControlled) onDecided?.(updated);
      else setFetched((prev) => prev.map((s) => (s.id === id ? updated : s)));
      return updated;
    });

  let body;
  if (state === "loading") {
    body = <p className="muted scope-state">Loading scope statements…</p>;
  } else if (state === "failed") {
    body = (
      <p className="scope-state scope-state--failed" role="alert">
        Couldn't load the scope statements. Check the connection and try again.
      </p>
    );
  } else if (statements.length === 0) {
    body = <p className="muted scope-state">{emptyText}</p>;
  } else {
    const confirmed = statements.filter((s) => s.status === "confirmed").length;
    const dismissed = statements.filter((s) => s.status === "dismissed").length;
    const groups = kinds.map((kind) => ({ kind, rows: statements.filter((s) => s.kind === kind) })).filter((g) => g.rows.length > 0);
    body = (
      <>
        <p className="scope-summary tabular">
          {plural(statements.length, "statement")} found · {confirmed} confirmed · {dismissed} dismissed
        </p>
        {groups.map((g) => (
          <div key={g.kind} className="scope-group">
            <h3 className="scope-group__title">{KIND_LABELS[g.kind]}</h3>
            <ul className="scope-list">
              {g.rows.map((s) => (
                <PlanLine key={s.id} line={s} onDecide={(change) => decide(s.id, change)} />
              ))}
            </ul>
          </div>
        ))}
      </>
    );
  }

  return (
    <section className="scope-card" aria-labelledby={headingId}>
      <header className="scope-head">
        <h2 id={headingId}>{title}</h2>
        <p className="muted">{description}</p>
      </header>
      {body}
    </section>
  );
}
