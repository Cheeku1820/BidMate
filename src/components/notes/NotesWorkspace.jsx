/* ============================================================
   NotesWorkspace.jsx — the notes-and-assumptions workspace
   (docs/superpowers/sdd/2026-08-28-notes-and-assumptions).

   Notes are not part of the review snapshot useReviewStore polls --
   Task 4's store methods (listNotes/createNote/updateNote/deleteNote)
   are a separate surface, because a note write never changes the
   takeoff itself (api.js's own comment on those methods). So this
   screen fetches its own list through `store` from useWorkspaceContext()
   rather than reading `snapshot.notes`, and refetches after every write
   rather than waiting on the shared poll.

   Every fact this screen states is doable through the structured form
   below (NoteForm.jsx) -- ROADMAP.md 2.6's constraint that anything
   sayable in a conversation panel must also be reachable through a
   form, field, or menu. This screen has no conversation panel at all
   (deliberately out of scope for this slice); it is the form.

   The apply banner ("Apply notes and re-run") wires a real re-run:
   gather this session's uploaded drawings (uploadedFiles.js), run them
   back through the engine with the unapplied context notes as the
   authoritative notes channel (engineClient.js's estimateProject), and
   hand the resulting payload to the approval-preserving merge
   (store.reprocess, Task 7). The summary names exactly what the server
   reported -- reclassified and preserved counts -- never a number this
   screen invented.

   Uploaded files are held in memory only for the session that uploaded
   them, and ProcessingStatus.jsx clears them the moment the project's
   first processing succeeds -- so "no drawings in memory" is the
   *common* state by the time an estimator is back here adding a note,
   not a rare edge case. That is handled plainly rather than surfacing
   as an obscure fetch failure.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { BadgeCheck, Building2, Calculator, FileText, HelpCircle, Layers, Tag } from "lucide-react";
import AppTopBar from "../shell/AppTopBar.jsx";
import Modal from "../Modal.jsx";
import NoteForm from "./NoteForm.jsx";
import ApplyNotesBanner from "./ApplyNotesBanner.jsx";
import { CATEGORY_LABELS, calculationEffect, SCOPE_LABELS, unappliedContextNotes } from "./noteVocabulary.js";
import { formatTimestamp } from "../../lib/format.js";
import { useWorkspaceContext } from "../project/useWorkspaceContext.js";
import { estimateProject } from "../../lib/engineClient.js";
import { getUploadedFiles } from "../../lib/uploadedFiles.js";

const SCOPE_FILTERS = ["company", "project", "sheet", "item"];

const EFFECT_ICON = { used: Calculator, reference: FileText, standard: Building2 };

function NoteStatusPill({ status }) {
  const Icon = status === "confirmed" ? BadgeCheck : HelpCircle;
  const label = status === "confirmed" ? "Confirmed" : "Open";
  return (
    <span className={"note-status note-status--" + status}>
      <Icon size={12} strokeWidth={2.6} aria-hidden="true" />
      {label}
    </span>
  );
}

function NoteCard({ note, onEdit, onDelete }) {
  const effect = calculationEffect(note);
  const EffectIcon = EFFECT_ICON[effect.tone];
  return (
    <div className="note-card">
      <div className="note-card__head">
        <h3 className="note-card__title">{note.title}</h3>
        <div className="note-card__actions">
          <button type="button" className="btn" onClick={() => onEdit(note)}>
            Edit
          </button>
          <button type="button" className="btn" onClick={() => onDelete(note)}>
            Delete
          </button>
        </div>
      </div>

      <div className="note-card__tags">
        <NoteStatusPill status={note.status} />
        <span className="pill pill--neutral">
          <Layers size={12} aria-hidden="true" />
          {SCOPE_LABELS[note.scope]}
        </span>
        <span className="pill pill--neutral">
          <Tag size={12} aria-hidden="true" />
          {CATEGORY_LABELS[note.category]}
        </span>
        <span className="pill pill--neutral">
          <EffectIcon size={12} aria-hidden="true" />
          {effect.label}
        </span>
        {note.rfiNeeded ? (
          <span className="note-flag">
            <HelpCircle size={11} aria-hidden="true" />
            RFI needed
          </span>
        ) : null}
      </div>

      <p className="note-card__body">{note.body}</p>

      <div className="note-card__meta">
        {note.authorName ? <span>{note.authorName}</span> : null}
        <span className="tabular">{formatTimestamp(note.updatedAt)}</span>
        {note.sourceRef ? <span>{note.sourceRef}</span> : null}
        {note.obsoleteAfterRevision ? <span>Clears after {note.obsoleteAfterRevision}</span> : null}
      </div>
    </div>
  );
}

function pluralize(count, singular, plural) {
  return `${count} ${count === 1 ? singular : plural}`;
}

export default function NotesWorkspace() {
  const { store, projectId, project, snapshot } = useWorkspaceContext();

  const [notes, setNotes] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [filterKey, setFilterKey] = useState(null); // null | "company" | "project" | "sheet" | "item" | "rfi"
  const [formNote, setFormNote] = useState(undefined); // undefined = closed, null = new, object = editing
  const [deletingNote, setDeletingNote] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [applyMessage, setApplyMessage] = useState(null);
  const [applyError, setApplyError] = useState(null);
  const [applyBusy, setApplyBusy] = useState(false);

  // The workspace's own sheets, for NoteForm's "which sheet" picker
  // (fix round 1, finding 3) -- read off the same shared snapshot
  // TakeoffSpreadsheet.jsx reads sheets/items from, not a second fetch.
  const sheets = snapshot?.sheets ?? [];

  const load = useCallback(() => {
    setLoadError(null);
    return store
      .listNotes(projectId)
      .then(setNotes)
      .catch((err) => setLoadError(err?.message || "Couldn't load notes. Check your connection and try again."));
  }, [store, projectId]);

  useEffect(() => {
    load();
  }, [load]);

  const hasNotes = Boolean(notes?.length);

  const visibleNotes = (notes ?? []).filter((note) => {
    if (!filterKey) return true;
    if (filterKey === "rfi") return note.rfiNeeded && note.status !== "confirmed";
    return note.scope === filterKey;
  });

  // Keyed on `usage` directly, the same field `unappliedContextNotes`
  // (the apply banner, below) keys on -- fix round 1's finding 1. Before
  // this fix the header counted `calculationEffect(n).tone !==
  // "reference"`, and a company-scoped note saved with the toggle off
  // had tone "standard" (not "reference"), so it was counted here while
  // the banner correctly ignored it: the one screen whose job is to say
  // what moves the number disagreed with itself. `calculationEffect`
  // now checks `usage` first too (noteVocabulary.js), so this could
  // read either way and still agree -- `usage === "context"` is kept
  // explicit here because it's the fact this count is actually about.
  const affectCount = (notes ?? []).filter((n) => n.usage === "context").length;
  const openRfiCount = (notes ?? []).filter((n) => n.rfiNeeded && n.status !== "confirmed").length;
  const unapplied = unappliedContextNotes(notes ?? []);

  const summaryParts = notes
    ? [
        pluralize(notes.length, "note", "notes"),
        affectCount > 0 ? `${affectCount} ${affectCount === 1 ? "affects" : "affect"} this estimate` : null,
        openRfiCount > 0 ? `${pluralize(openRfiCount, "open RFI", "open RFIs")}` : null,
      ].filter(Boolean)
    : [];

  async function handleSave(fields) {
    if (formNote) {
      await store.updateNote(formNote.id, fields);
    } else {
      await store.createNote(projectId, fields);
    }
    setFormNote(undefined);
    await load();
  }

  // Deletion is not undoable (there is no undo_apply.py case for a note
  // action, and this screen carries no undo control of its own), which
  // is exactly why a failed request can't be allowed to look like it
  // worked. Fix round 1, finding 2: this used to have no catch at all --
  // a rejected promise left the dialog open with no message and the
  // note still there, while nothing told the estimator the delete
  // hadn't happened. Now a failure keeps the dialog open and surfaces
  // the store's own message (the server's already name a recovery
  // action) right next to the confirm button, rather than closing on
  // an assumption.
  function openDelete(note) {
    setDeleteError(null);
    setDeletingNote(note);
  }

  function closeDelete() {
    setDeletingNote(null);
    setDeleteError(null);
  }

  async function handleDeleteConfirmed() {
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await store.deleteNote(deletingNote.id);
      setDeletingNote(null);
      await load();
    } catch (err) {
      setDeleteError(err?.message || "This note couldn't be deleted. Try again.");
    } finally {
      setDeleteBusy(false);
    }
  }

  // The real re-run. Only `usage === "context"` notes are the engine's
  // authoritative notes channel (a reference-only note must never reach
  // the classifier) -- `unapplied` is already exactly that set, keyed
  // the same way the banner counts it, so the two can never disagree
  // about which notes this run is for.
  async function handleApplyAndRerun() {
    setApplyError(null);
    setApplyBusy(true);
    try {
      const uploaded = getUploadedFiles(projectId);
      if (uploaded.length === 0) {
        setApplyError(
          "The source drawings for this project aren't available in this browser. Upload the drawing set again to re-run the takeoff.",
        );
        return;
      }
      const contextNotes = unapplied.map((n) => ({
        scope: n.scope,
        title: n.title,
        body: n.body,
        source_ref: n.sourceRef,
      }));
      const payload = await estimateProject(uploaded, project?.location || "", contextNotes);
      const result = await store.reprocess(projectId, payload);
      const id = Date.now();
      setApplyMessage({
        id,
        text: `${result.reclassified} ${result.reclassified === 1 ? "item" : "items"} reclassified. ${result.preserved} approved ${result.preserved === 1 ? "item was" : "items were"} left unchanged.`,
      });
      setTimeout(() => setApplyMessage((m) => (m && m.id === id ? null : m)), 5000);
      await load();
    } catch (err) {
      setApplyError(err?.message || "The re-run couldn't be completed. Try again.");
    } finally {
      setApplyBusy(false);
    }
  }

  const addNoteButton = (
    <button type="button" className="btn btn--primary" onClick={() => setFormNote(null)}>
      Add note
    </button>
  );

  return (
    <>
      <AppTopBar title="Notes & assumptions" primaryAction={hasNotes ? addNoteButton : undefined} />

      <div className="page">
        <h1 className="page-heading">Notes & assumptions</h1>
        <p className="page-intro">
          Record what the drawings don't say — an existing condition, a scope exclusion, an instruction from the
          customer. Mark a note to feed the takeoff and it is used the next time the takeoff is re-run; otherwise
          it stays here as documentation only.
        </p>

        {loadError ? (
          <div className="load-error" role="alert">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={load}>
              Try again
            </button>
          </div>
        ) : null}

        {notes === null && !loadError ? <p className="muted">Loading notes…</p> : null}

        {notes && !hasNotes ? (
          <div className="empty-state">
            <h2>No notes yet</h2>
            <p>Add one to document an assumption, exclusion, or instruction the drawings don't carry.</p>
            {addNoteButton}
          </div>
        ) : null}

        {notes && hasNotes ? (
          <>
            <p className="notes-summary tabular">{summaryParts.join(" · ")}</p>

            <ApplyNotesBanner
              count={unapplied.length}
              action={
                <button type="button" className="btn btn--primary" onClick={handleApplyAndRerun} disabled={applyBusy}>
                  {applyBusy ? "Applying…" : "Apply notes and re-run"}
                </button>
              }
            />
            {applyMessage ? (
              <p className="notes-apply-banner-note tabular" role="status">
                {applyMessage.text}
              </p>
            ) : null}
            {applyError ? (
              <div className="warncard warncard--missing" role="alert">
                <p>{applyError}</p>
              </div>
            ) : null}

            <div className="filter-chips" role="group" aria-label="Filter notes">
              <button
                type="button"
                className="filter-chip"
                aria-pressed={filterKey === null}
                onClick={() => setFilterKey(null)}
              >
                All notes
              </button>
              {SCOPE_FILTERS.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="filter-chip"
                  aria-pressed={filterKey === key}
                  onClick={() => setFilterKey(key)}
                >
                  {SCOPE_LABELS[key]}
                </button>
              ))}
              <button
                type="button"
                className="filter-chip"
                aria-pressed={filterKey === "rfi"}
                onClick={() => setFilterKey("rfi")}
              >
                RFI needed
              </button>
            </div>

            {visibleNotes.length === 0 ? (
              <div className="empty-state">
                <h2>No notes match</h2>
                <p>Try a different filter.</p>
                <button type="button" className="btn" onClick={() => setFilterKey(null)}>
                  Clear filter
                </button>
              </div>
            ) : (
              <div className="notes-list">
                {visibleNotes.map((note) => (
                  <NoteCard key={note.id} note={note} onEdit={setFormNote} onDelete={openDelete} />
                ))}
              </div>
            )}
          </>
        ) : null}
      </div>

      {formNote !== undefined ? (
        <NoteForm note={formNote} sheets={sheets} onSave={handleSave} onClose={() => setFormNote(undefined)} />
      ) : null}

      {deletingNote ? (
        <Modal
          title="Delete note"
          onClose={closeDelete}
          foot={
            <>
              <button type="button" className="btn" onClick={closeDelete} disabled={deleteBusy}>
                Cancel
              </button>
              <button type="button" className="btn btn--danger" onClick={handleDeleteConfirmed} disabled={deleteBusy}>
                {deleteBusy ? "Deleting…" : "Delete note"}
              </button>
            </>
          }
        >
          {deleteError ? (
            <div className="warncard warncard--missing" role="alert">
              <p>{deleteError}</p>
            </div>
          ) : null}
          <p>Delete “{deletingNote.title}”? This can't be undone.</p>
        </Modal>
      ) : null}
    </>
  );
}
