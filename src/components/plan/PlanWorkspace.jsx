/* ============================================================
   PlanWorkspace.jsx — the project plan: what the documents say, for an
   electrical sub. docs/specs/project-plan-screen.md.

   Sits after Confirm drawings and before Processing, and owns Start
   takeoff. Everything on it is derived server-side on every read from
   what the read job stored; this screen fetches store.getPlan, polls
   while a drawing set is still being read (same 3 s screen D uses),
   and re-fetches after any write so the undecided count and the
   questions (which depend on the other sections) stay true.

   Six sections, one row shape (PlanLine). Scope and Exclusions are two
   views of the plan's one scope array -- a decision in either updates
   both. Nothing here is counted; no quantity appears.

   Start takeoff carries screen D's exact rules: disabled while a
   drawing set is reading (READING_HELP, the sentence the server also
   answers with), a run already in flight is treated as started, any
   other refusal is shown next to the button.
   ============================================================ */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { formatTimestamp } from "../../lib/format.js";
import PlanLine from "./PlanLine.jsx";
import PlanSection from "./PlanSection.jsx";
import PhaseSection from "./PhaseSection.jsx";
import QuestionLine from "./QuestionLine.jsx";
import ScopeSection from "./ScopeSection.jsx";

const READ_POLL_MS = 3000;
const READING_HELP = "A drawing set is still being read. Wait for it to finish before starting the takeoff.";
const LOAD_FAILED = "Couldn't load the plan. Check the connection and try again.";

export default function PlanWorkspace() {
  const { store, projectId } = useWorkspaceContext();
  const navigate = useNavigate();
  const [plan, setPlan] = useState(null);
  const [state, setState] = useState("loading"); // loading | loaded | failed
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState("");

  const aliveRef = useRef(true);
  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const load = useCallback(
    () =>
      store
        .getPlan(projectId)
        .then((p) => {
          if (!aliveRef.current) return;
          setPlan(p);
          setState("loaded");
        })
        .catch(() => {
          if (!aliveRef.current) return;
          setState((s) => (s === "loaded" ? s : "failed"));
        }),
    [store, projectId],
  );

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!plan?.reading) return undefined;
    const t = setInterval(load, READ_POLL_MS);
    return () => clearInterval(t);
  }, [plan?.reading, load]);

  // Every write is followed by a re-read: a decision changes the
  // undecided count, an added phase silences a question, an answer
  // creates a note. The server is the one place the plan is assembled.
  const after = (promise) => promise.then((r) => load().then(() => r));

  const decideLine = (key, change) => after(store.decidePlanLine(projectId, key, change));
  const onScopeDecided = (updated) => {
    setPlan((p) => (p ? { ...p, scope: p.scope.map((s) => (s.id === updated.id ? updated : s)) } : p));
    load();
  };

  const canStart = state === "loaded" && plan.hasDrawings && !plan.reading && !starting;
  const start = () => {
    if (!canStart) return;
    setStarting(true);
    setStartError("");
    store
      .startTakeoff(projectId)
      .then(() => {
        if (!aliveRef.current) return;
        navigate(`/projects/${projectId}/processing`);
      })
      .catch((err) => {
        if (!aliveRef.current) return;
        if (err?.code === "run_in_flight") {
          navigate(`/projects/${projectId}/processing`);
          return;
        }
        setStarting(false);
        setStartError(
          typeof err?.code === "string" && err.message
            ? err.message
            : "Couldn't start the takeoff. Check the connection and try again.",
        );
      });
  };

  const startButton = (
    <button type="button" className="btn btn--primary" disabled={!canStart}
            aria-describedby={plan?.reading ? "plan-start-help" : undefined} onClick={start}>
      Start takeoff
    </button>
  );

  let body;
  if (state === "loading") {
    body = <p className="muted">Reading the documents…</p>;
  } else if (state === "failed") {
    body = <p className="scope-state scope-state--failed" role="alert">{LOAD_FAILED}</p>;
  } else if (!plan.hasDrawings && plan.scope.length === 0 && plan.questions.length === 0) {
    body = (
      <p className="muted">
        <Link to={`/projects/${projectId}/documents`}>Upload documents to build the plan</Link>
      </p>
    );
  } else {
    body = (
      <>
        <ScopeSection store={store} projectId={projectId} statements={plan.scope} onDecided={onScopeDecided} />

        <PlanSection id="plan-specs-heading" title="Specification sections"
                     description="Every Division 26, 27, and 28 section found in the uploaded specifications and addenda."
                     emptyText="No specification sections were found in the uploaded documents.">
          {plan.specs.map((l) => <PlanLine key={l.key} line={l} onDecide={(c) => decideLine(l.key, c)} />)}
        </PlanSection>

        <PlanSection id="plan-schedules-heading" title="Schedules and legends"
                     description="Each schedule or legend sheet in the drawing set, and each schedule found on a plan sheet."
                     emptyText="No schedule or legend sheet was found in the drawing set.">
          {plan.schedules.map((l) => <PlanLine key={l.key} line={l} onDecide={(c) => decideLine(l.key, c)} />)}
        </PlanSection>

        <PhaseSection phases={plan.phases} onDecide={decideLine}
                      onAdd={(name) => after(store.addPlanPhase(projectId, name))}
                      onRemove={(phaseId) => after(store.removePlanPhase(projectId, phaseId))} />

        <ScopeSection store={store} projectId={projectId} statements={plan.scope} onDecided={onScopeDecided}
                      kinds={["excluded", "by_others"]} title="Exclusions" headingId="plan-exclusions-heading"
                      description="What the documents leave out of this bid, or leave to others. The same lines as under Scope; a decision here is the same decision."
                      emptyText="The documents do not state anything as excluded or by others." />

        <PlanSection id="plan-questions-heading" title="Open questions"
                     description="What the documents did not answer. An answer is saved as a note and read by the next takeoff run."
                     emptyText="Nothing is open.">
          {plan.questions.map((q) => (
            <QuestionLine key={q.key} question={q} notesHref={`/projects/${projectId}/notes`}
                          onAnswer={(body) => after(store.answerPlanQuestion(projectId, q.key, body))}
                          onDismiss={() => decideLine(q.key, { status: "dismissed" })}
                          onReopen={() => decideLine(q.key, { status: "found" })} />
          ))}
        </PlanSection>
      </>
    );
  }

  const undecided = plan?.undecided ?? 0;

  return (
    <>
      <AppTopBar title="Project plan" primaryAction={startButton}>
        <Link className="btn" to={`/projects/${projectId}/documents/confirm`}>Back to confirm drawings</Link>
      </AppTopBar>
      <div className="workspace-body">
        <div className="page plan-page">
          <p className="muted page-intro">
            What the documents say this bid is. Confirm each line, correct it, or dismiss it; the takeoff reads what you leave standing.
          </p>
          {state === "loaded" ? (
            <p className="plan-status tabular">
              <span>{`${undecided} ${undecided === 1 ? "line" : "lines"} not yet decided`}</span>
              {plan.readAt ? <span>{` · Read ${formatTimestamp(plan.readAt)}`}</span> : null}
            </p>
          ) : null}
          <p id="plan-start-help" className="footer-help">{plan?.reading ? READING_HELP : null}</p>
          {startError ? <p className="scope-state scope-state--failed" role="alert">{startError}</p> : null}
          {body}
        </div>
      </div>
    </>
  );
}
