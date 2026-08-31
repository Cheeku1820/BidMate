/* ============================================================
   ApplyNotesBanner.jsx — the strip that says a note marked "feeds the
   takeoff" hasn't been carried into it yet.

   Shared by NotesWorkspace.jsx (where it triggers the actual re-run) and
   Workspace.jsx (where it only links back to the notes screen), so both
   screens agree on the wording instead of drifting apart the way two
   independently-written banners eventually do. `action` is the one
   piece that differs between them -- a button that performs the re-run,
   or a link that sends the estimator to the one screen that can.

   ROADMAP.md 2.6 / DESIGN.md: exactly one place triggers a re-run. This
   component never decides what that place's control does; it only
   renders whatever the caller hands it as `action`.
   ============================================================ */

export default function ApplyNotesBanner({ count, action }) {
  if (count <= 0) return null;
  return (
    <div className="notes-apply-banner">
      <p className="tabular">
        {count} {count === 1 ? "note" : "notes"} marked to feed the takeoff {count === 1 ? "hasn't" : "haven't"} been
        carried into it yet.
      </p>
      {action}
    </div>
  );
}
