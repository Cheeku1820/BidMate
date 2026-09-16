/* ============================================================
   SheetProgressList.jsx — the per-sheet progress of a takeoff run, as
   store.getProcessing reports it.

   Shared by the processing screen (E) and the notes screen's
   apply-and-re-run, so a run reads the same way wherever it is
   watched. The stage words live HERE and nowhere else: `waiting`,
   `finding`, `checking`, `complete`, `attention` are the server's
   closed set (api/app/jobs/status.py), and the estimator only ever
   sees the word for each.

   Every stage is an icon plus a word, never a hue alone (CLAUDE.md).
   A complete sheet's check is blue, not green -- green is reserved
   for estimator-approved content, and "done processing" is not that.
   `attention` is the same *Needs attention* the review labels use,
   in the same amber, because that is what a sheet the run couldn't
   finish is: something an estimator has to look at.

   What a sheet's row carries beneath it -- `reason` when it needs
   attention, `note` when it completed with a caveat (schedules not
   checked, nothing to count on a non-plan sheet) -- is the server's
   own words. Silence must never read as completeness, so a note is
   rendered wherever the server sends one.

   Documents the worker couldn't read list ABOVE the sheets with their
   reason: a set that lost a file is a fact about the whole run, not
   about any one sheet in it.
   ============================================================ */

import { AlertTriangle, CheckCircle2, FileText, Loader2 } from "lucide-react";

// How often a screen watching a run asks again. Matches screens C and
// D; nothing here needs to be faster than the worker. Lives with the
// list so both screens that watch a run share the cadence and the
// stop rule below, rather than one screen importing from another.
export const RUN_POLL_MS = 3000;

/** Whether a run still needs watching: no run yet (one was just asked
 *  for), or one the queue is still working. Terminal states are
 *  `complete` and `complete_with_failures`. */
export function isRunActive(run) {
  return run == null || run.state === "queued" || run.state === "running";
}

export const STAGE_WORDS = {
  waiting: "Waiting",
  finding: "Finding electrical items",
  checking: "Checking schedules",
  complete: "Complete",
  attention: "Needs attention",
};

function StageIcon({ stage }) {
  if (stage === "complete") return <CheckCircle2 aria-hidden="true" size={16} className="ink-blue" />;
  if (stage === "attention") return <AlertTriangle aria-hidden="true" size={16} className="ink-amber" />;
  if (stage === "finding" || stage === "checking") return <Loader2 aria-hidden="true" size={16} className="spin" />;
  return <span className="processing-dot" aria-hidden="true" />;
}

function SheetRow({ sheet }) {
  const word = STAGE_WORDS[sheet.stage] ?? STAGE_WORDS.waiting;
  const stageClass = "processing-stage" + (sheet.stage === "complete" ? " is-complete" : "") + (sheet.stage === "attention" ? " is-attention" : "");
  return (
    <li className="processing-row">
      <span className="processing-icon">
        <StageIcon stage={sheet.stage} />
      </span>
      <span className="processing-sheet">{sheet.number}</span>
      <span className="processing-title">{sheet.title}</span>
      <span className={stageClass}>
        <span className="processing-word">{word}</span>
        {sheet.stage === "complete" ? (
          <>
            {" · "}
            <span className="tabular">{sheet.itemCount}</span> {sheet.itemCount === 1 ? "item" : "items"}
          </>
        ) : null}
      </span>
      {sheet.reason ? <p className="processing-note processing-note--attention">{sheet.reason}</p> : null}
      {sheet.note ? <p className="processing-note">{sheet.note}</p> : null}
    </li>
  );
}

export function progressLine(run) {
  const noun = run.totalCount === 1 ? "sheet" : "sheets";
  return `${run.completeCount} of ${run.totalCount} ${noun} complete`;
}

export default function SheetProgressList({ run, documents }) {
  const failedDocuments = (documents ?? []).filter((d) => d.state === "failed");

  return (
    <div className="processing-progress">
      {failedDocuments.length > 0 ? (
        <ul className="processing-list processing-list--documents" aria-label="Documents that couldn't be read">
          {failedDocuments.map((d) => (
            <li key={d.id} className="processing-row">
              <span className="processing-icon">
                <AlertTriangle aria-hidden="true" size={16} className="ink-red" />
              </span>
              <span className="processing-icon">
                <FileText aria-hidden="true" size={16} />
              </span>
              <span className="processing-title">{d.filename}</span>
              <span className="processing-stage is-failed">Couldn't be read</span>
              {d.reason ? <p className="processing-note processing-note--failed">{d.reason}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {run ? (
        <>
          <p className="processing-count tabular" role="status" aria-live="polite">
            {progressLine(run)}
          </p>
          {run.sheets.length > 0 ? (
            <ul className="processing-list" aria-label="Sheets">
              {run.sheets.map((sheet) => (
                <SheetRow key={sheet.id} sheet={sheet} />
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
