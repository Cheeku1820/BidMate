/* ============================================================
   AppTopBar.jsx — spec §4.3's persistent top bar.

   Company-level screens (projects dashboard, new project, project
   overview) render this for their title, save state, and primary
   action. The review workspace keeps its own TopBar.jsx unchanged in
   this task — it already carries save state, undo/redo, and presence
   for that one screen, and splitting those out is a larger refactor
   than this task's brief covers (task-6-brief.md's ambiguity
   resolution 3). This component exists so every *other* screen has
   somewhere to put the same save-state convention without duplicating
   TopBar.jsx's markup.
   ============================================================ */

export default function AppTopBar({ title, subtitle, saveState, children, primaryAction }) {
  return (
    <header className="app-top-bar">
      <div className="app-top-bar-identity">
        <span className="app-top-bar-title">{title}</span>
        {subtitle ? <span className="app-top-bar-subtitle">{subtitle}</span> : null}
      </div>
      <div className="app-top-bar-tools">
        {saveState ? (
          // .savestate (no hyphen) is the stylesheet's actual class,
          // shared with TopBar.jsx — .save-state doesn't exist in
          // styles.css and would render unstyled.
          <span className="savestate tabular" role="status" aria-live="polite">
            {saveState}
          </span>
        ) : null}
        {children}
        {primaryAction}
      </div>
    </header>
  );
}
