# BidMate — design

How the product looks and behaves. `SPEC.md` says what each screen contains; this file says how every screen is drawn and how interactions work, so that eleven screens come out as one product.

---

## 1. Personality

Professional, dependable, precise, approachable. A modern estimating instrument built for daily work — not a futuristic AI demonstration. Familiar controls, one primary action per screen, generous spacing on setup screens, controlled density in the review table. No cards for their own sake, no gradients, no glass, no decorative animation, no hover-only controls.

## 2. Design tokens

Set once in `web/src/styles/tokens.css` as CSS variables and mapped into `tailwind.config.ts` so classes like `bg-surface`, `text-ink-2`, `border-line-1`, `text-status-attention` exist. Never write a hex value in a component.

```
Surfaces      --paper-0 #f7f5f0   --paper-1 #fbfaf7   --surface #ffffff   --canvas #ecebe5   --sheet #fdfcf9
Lines         --line-1 #e4e1d9    --line-2 #cfcbc0    --line-3 #a9a49a
Ink           --ink-1 #1b1a18     --ink-2 #56534d     --ink-3 #86827a
Blue (primary, selection, Ready to review)   --blue #23528f   --blue-600 #1b4275   --blue-tint #e8f0fa   --blue-line #b6cde9
Green (Estimator approved ONLY)              --green #1c6f47  --green-tint #e6f3ec  --green-line #b2d8c3
Amber (Needs attention)                      --amber #9c5f06  --amber-tint #fbf0dc  --amber-line #e8cf9c
Red (Missing information, blocking errors)   --red #b0322a    --red-tint #fbe9e7    --red-line #edbdb7
Slate (note status — never an item status)   --slate #3d5566  --slate-tint #e8eef1  --slate-line #c3d1d8
Plum (note kind)                             --plum #5b4570   --plum-tint #efe9f3   --plum-line #d3c3dd
Radii         --r-sm 4px  --r-md 6px  --r-lg 10px
Type          system sans stack; 16px body; 14px table; 13px meta; tabular numerals on every number
Spacing       4px grid; page padding 24px; panel padding 12–16px
```

Status role → token: `ready` blue, `attention` amber, `missing` red, `approved` green. Slate/plum exist so a note's status pill can never be mistaken for an item's.

## 3. The component kit (`web/src/components/domain/`)

Built once in milestone 1 from shadcn/ui primitives; every screen composes these. Names are the public API.

| Component | Contract |
|---|---|
| `StatusPill status` | Hue + icon (`CircleDot` ready, `AlertTriangle` attention, `CircleOff` missing, `CheckCircle2` approved) + text label. Never color alone. |
| `NotePill status\|kind` | Slate/plum. Distinct component, so it cannot take an item status. |
| `WarningCard warning` | Title, then the four fields as labelled rows: *Found · Why it matters · What to check · Where*. |
| `DataGrid` | Keyboard-navigable table: sortable/resizable columns, column visibility, group-by, inline editors (text, number, select), row selection, sticky header, footer row. Tabular numerals on numeric columns. |
| `PageHeader title, subtitle?, primaryAction?, actions?` | One primary button, right-aligned. |
| `SaveState state` | `Saving…` / `Saved 2:41 PM` / `Couldn't save — retrying`. |
| `UndoToast label, onUndo` | Bottom-left, 5 s, inline **Undo**. |
| `EmptyState heading, body, primary, secondary?` | For every list and grid. |
| `Drawer` (bottom, collapsible strip) and `SidePanel` (right, 330 px) | The blueprint's drawer and item panel; reused by others. |
| `ConfirmDialog` | For deleting documents, discarding corrections, replacing a revision set — nothing else. |
| `Symbol type` | Hand-drawn SVG electrical symbols by drafting convention: receptacle (circle, bisecting line), switch (circle + S), panel (crossed rectangle), luminaire (circle + cross / rectangle), data (triangle), junction box (square + J), disconnect, motor, exit/emergency. |
| `Marker item, selected` | `Symbol` glyph + status ring + warning badge. Three independent channels. |

Interface icons: `lucide-react`. Copy: sentence case; no exclamation marks; no "successfully", "please", "oops".

## 4. Layout

- Desktop only, 1280 px minimum, optimized at 1440. Below 1024 px the review workspace shows "Use a larger screen to review drawings"; other screens simply stack.
- App shell: `grid-template-columns: auto minmax(0,1fr) auto` — rail (232 px company / project; 52 px collapsed), the screen, the conversation panel (340 px / 44 px strip). Inside a project the rail is the project nav; the breadcrumb goes back to company level.
- On the blueprint the rail starts collapsed and, under 1440 px, opening the conversation panel collapses the sheets list, so the canvas stays the largest element.
- Long pages scroll inside the main column; the rail and panel stay fixed.

## 5. Interaction rules

**Autosave.** Every edit writes immediately. `SaveState` in the top bar; an `UndoToast` per action, phrased in the estimator's words ("Approved 20A duplex receptacle"). The toast is a convenience; undo in the top bar never expires within the session.

**Undo.** Per session, client-side (`SPEC.md` §11). Tooltip on the button names what will be reversed. Scale confirmation is one compound undo.

**Blueprint ↔ spreadsheet.** One selection in shared state. Selecting a marker opens the item and scrolls the grid to it; selecting a row centers the blueprint on the marker and selects it. Editing in either place updates both, the drawer, and the audit history in the same action.

**Status and layers.** Marker hue = status, glyph = type, badge = warning. Layer toggles filter what is drawn, never what is counted. Measured items whose scale is unconfirmed are drawn dashed.

**Warnings.** Rendered only through `WarningCard`. Never mention models, confidence, or processing.

**Finish review.** A dialog with two groups: Missing information (blocks; each row has "Go to item", which closes the dialog and selects it); Needs attention (allowed behind a checkbox whose label says "These become allowances in the exported takeoff"; the checkbox resets if new attention items appear). No "proceed anyway".

**Calibration.** Two clicks on a known dimension; a banner states which click is next; confirm asks for the real length; produces the same undoable action as choosing a scale.

**Revisions.** Each sheet carries revision + date; the active set is named in the top bar. A superseded sheet stays browsable read-only, contributes nothing to totals, and shows a "Superseded by …" banner.

**Processing.** Stage words, never times. A failed sheet fails alone.

**Conversation panel.** See `SPEC.md` §8. The composer goes read-only while an answer streams (never disabled — focus must not fall onto the shortcut keys). Autoscroll only while already at the bottom.

## 6. Keyboard

Single keys, suppressed while focus is in a text field or the panel's composer:

`A` approve · `E` edit · `R` reject · `J`/`K` next/previous item · `+`/`−` zoom · `0` fit · `Esc` close panel/dialog · `⌘/Ctrl+Z` undo · `⌘/Ctrl+Shift+Z` redo · `/` focus search. A visible shortcut reference under Help.

## 7. Required states

Every screen has: empty, loading, error (copy names the recovery action — never "Something went wrong" alone), and its own of: uploading · processing · partial success · complete · upload failure · unsupported document · password-protected · missing scale · conflicting revision · unknown symbol · no search results · unsaved edit · saved · offline ("Reconnecting — your edits will send when the connection returns") · permission denied · export ready · export failure.

Skeletons for lists and grids; a spinner only inside a button.

## 8. Accessibility

WCAG 2.2 AA. Visible focus rings on everything. Markers are buttons (`aria-label="{name}, {status label}"`), reachable by keyboard, `Enter`/`Space` selects. Every form field has a persistent visible label. `prefers-reduced-motion` disables the few transitions. Status never by color alone (see §3). Live regions: one `role="status"` for save state, one for the conversation panel; never a live region on a list that mutates per keystroke. Touch targets ≥ 40 × 40 even on desktop.

## 9. Copy register

- Product words: "found", "detected", "suggested", "needs attention", "missing information", "estimator approved". Never: "the AI thinks", "confidence 87%", model names, "assistant".
- The panel and the warnings read as a colleague who has the drawings open: specific, located ("E2.1 title block"), short.
- Errors: what happened + what to do. "That change couldn't be saved. Try again." "This file is password-protected. Upload an unlocked copy."
- Numbers: tabular numerals; quantities to two decimals only when fractional; money with thousands separators; hours to two decimals.
