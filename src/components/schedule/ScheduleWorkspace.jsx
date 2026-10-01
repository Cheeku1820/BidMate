/* ============================================================
   ScheduleWorkspace.jsx — Phases and schedule
   (docs/specs/phases-and-timeline.md §6).

   Renders what GET /schedule returns and derives no number of its own:
   a duration, a date, a crew, an order-by all come from the API. The
   screen's job is to show them, say which are computed and which are
   the estimator's, and route every change through the store.

   Nothing here changes what is counted. A phase is a grouping of items
   that already exist, so no total, status, or approval moves when one
   is added, renamed, or deleted.
   ============================================================ */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AppTopBar from "../shell/AppTopBar.jsx";
import { saveStateText } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { useSchedule } from "./useSchedule.js";
import PhaseList from "./PhaseList.jsx";
import StageBars from "./StageBars.jsx";
import StageEditor from "./StageEditor.jsx";
import ManpowerChart from "./ManpowerChart.jsx";
import LongLeadList from "./LongLeadList.jsx";
import { COPY } from "./scheduleCopy.js";

export default function ScheduleWorkspace() {
  const { store, projectId, snapshot, saved } = useWorkspaceContext();
  const { schedule, loadError, saveError, reload, mutate } = useSchedule();
  const [selectedBar, setSelectedBar] = useState(null); // { phaseId, stage }

  const sheets = snapshot?.sheets ?? [];
  const items = snapshot?.items ?? [];
  const hasBars = useMemo(
    () => Boolean(schedule?.phases.some((phase) => phase.bars.length > 0)),
    [schedule],
  );

  const actions = {
    onAddPhase: (name, afterPhaseId) =>
      mutate(() => store.createPhase(projectId, { name, afterPhaseId }), `Added ${name || "a phase"}`),
    onRename: (phaseId, name) => mutate(() => store.editPhase(phaseId, { name }), `Renamed to ${name}`),
    onDates: (phaseId, dates) => mutate(() => store.editPhase(phaseId, dates), "Changed phase dates"),
    onReorder: (phaseId, sortOrder) => mutate(() => store.editPhase(phaseId, { sortOrder }), "Moved phase"),
    onDelete: (phaseId, targetName) => {
      const phase = schedule.phases.find((row) => row.id === phaseId);
      if (!window.confirm(COPY.deletePhaseConfirm(phase?.name ?? "this phase", targetName))) return null;
      return mutate(() => store.deletePhase(phaseId), "Removed phase");
    },
    onAssignSheets: (phaseId, sheetIds) => mutate(() => store.setPhaseSheets(phaseId, sheetIds), "Moved sheets"),
    onLineHours: (phaseId, lineId, hours) =>
      mutate(
        () => store.setPhaseLine(phaseId, lineId, hours),
        hours == null ? COPY.resetToComputed : `Set to ${hours} hours`,
      ),
    onPropose: () => store.proposePhases(projectId, null),
    onApplyProposal: (proposal) =>
      mutate(
        () => store.applyProposedPhases(projectId, proposal),
        `Set up ${proposal.phases.length} phases`,
      ),
  };

  const onStagePlan = (phaseId, stage, changes) =>
    mutate(() => store.setStagePlan(phaseId, stage, changes), "Changed stage");

  const onLeadTime = (itemId, changes) =>
    mutate(
      () => store.setLeadTime(itemId, changes),
      changes.leadWeeks === null ? "Cleared lead time" : "Changed lead time",
    );

  const selectedPhase = selectedBar ? schedule?.phases.find((phase) => phase.id === selectedBar.phaseId) : null;
  const selected = selectedPhase?.bars.find((bar) => bar.stage === selectedBar.stage) ?? null;

  return (
    <>
      <AppTopBar title={COPY.title} saveState={saveStateText(saved)} />

      <div className="page page--fill workspace--schedule">
        <h1 className="page-heading">{COPY.title}</h1>
        <p className="muted">{COPY.intro}</p>

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={reload}>Try again</button>
          </div>
        ) : null}

        {saveError ? (
          <div className="load-error" role="alert">
            <p>{saveError}</p>
          </div>
        ) : null}

        {schedule === null && !loadError ? <p className="muted">Loading the schedule…</p> : null}

        {schedule !== null && !loadError ? (
          <>
            <PhaseList schedule={schedule} sheets={sheets} {...actions} />

            {schedule.unscheduledCount > 0 ? (
              <p className="schedule-note tabular">
                {schedule.unscheduledNote} — <Link to={`/projects/${projectId}/labor`}>Labor</Link>
              </p>
            ) : null}

            {hasBars ? (
              <>
                {schedule.relative ? <p className="muted">{COPY.relativeAxis}</p> : null}
                {schedule.defaultsInUse.splits ? <p className="muted">{COPY.defaultSplit}</p> : null}
                {schedule.defaultSplitCount > 0 ? (
                  <p className="muted tabular">{COPY.defaultSplitCount(schedule.defaultSplitCount)}</p>
                ) : null}

                <div className="schedule-body">
                  <StageBars schedule={schedule} selected={selectedBar} onSelect={setSelectedBar} />
                  {selected ? (
                    <StageEditor
                      phase={selectedPhase}
                      bar={selected}
                      onChange={(changes) => onStagePlan(selectedBar.phaseId, selectedBar.stage, changes)}
                      onClose={() => setSelectedBar(null)}
                    />
                  ) : null}
                </div>

                <ManpowerChart schedule={schedule} />
              </>
            ) : (
              <div className="empty-state">
                <h2>Nothing to schedule yet</h2>
                <p>
                  Labor hours come from the <Link to={`/projects/${projectId}/labor`}>Labor</Link> workspace.
                </p>
              </div>
            )}

            <LongLeadList schedule={schedule} items={items} onLeadTime={onLeadTime} />
          </>
        ) : null}
      </div>
    </>
  );
}
