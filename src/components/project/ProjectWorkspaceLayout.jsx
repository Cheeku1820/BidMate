/* ============================================================
   ProjectWorkspaceLayout.jsx — the state every project workspace
   shares.

   The blueprint and the takeoff spreadsheet are two views of one set of
   records (spec §10, DESIGN.md's "Blueprint and table
   synchronization"), which means exactly one store subscription and
   exactly one selection between them. Before this layout existed, both
   lived inside the blueprint workspace, so a sibling route would have
   opened a second subscription with its own poll and its own idea of
   what was selected -- two views that agree only by coincidence.

   Selection lives here rather than in either view, which is what
   DESIGN.md asks for in so many words.

   The `key={projectId}` remount that used to sit in Workspace.jsx moves
   here for the same reason it existed there: on a project switch the
   previous project's snapshot and selection must not be visible for the
   duration of the fetch, and a targeted "clear these fields" patch has
   to re-derive by hand what a remount gets for free.
   ============================================================ */

import { useCallback, useEffect, useState } from "react";
import { Outlet, useParams } from "react-router-dom";
import { useReviewStore } from "../../lib/useReviewStore.js";

export default function ProjectWorkspaceLayout({ store, me, onSignedOut }) {
  const { projectId } = useParams();
  return (
    <LayoutForProject
      key={projectId}
      projectId={projectId}
      store={store}
      me={me}
      onSignedOut={onSignedOut}
    />
  );
}

function LayoutForProject({ store, me, onSignedOut, projectId }) {
  // Declared ahead of useReviewStore() deliberately. React runs a
  // fiber's passive effects in the order their useEffect calls happened
  // during render, and useReviewStore's mount effect (the one that
  // fetches) is registered inside that call -- so declaring this first
  // is what guarantees the store is pointed at this project before the
  // first fetch, rather than a race that happens to work today.
  useEffect(() => {
    store.useProject(projectId);
  }, [store, projectId]);

  const review = useReviewStore(store, { onSignedOut });

  const [sheetId, setSheetId] = useState(null);
  const [selectedItemId, setSelectedItemId] = useState(null);

  const sheets = review.snapshot?.sheets ?? [];
  const items = review.snapshot?.items ?? [];

  useEffect(() => {
    if (sheets.length && (!sheetId || !sheets.some((s) => s.id === sheetId))) {
      setSheetId(sheets[0].id);
    }
  }, [sheets, sheetId]);

  // Selecting an item on another sheet brings the sheet with it.
  // Without this the blueprint would sit on one sheet while the table
  // highlighted a row belonging to another, and the estimator would have
  // two views telling them different things about what they are
  // looking at.
  const selectItem = useCallback(
    (itemId) => {
      setSelectedItemId(itemId);
      if (!itemId) return;
      const item = items.find((i) => i.id === itemId);
      if (item && item.sheetId !== sheetId) setSheetId(item.sheetId);
    },
    [items, sheetId],
  );

  // A selected item that has been deleted, or that belongs to a sheet
  // that just became superseded, must not stay selected -- the detail
  // panel would render a record that no longer exists.
  useEffect(() => {
    if (selectedItemId && !items.some((i) => i.id === selectedItemId)) {
      setSelectedItemId(null);
    }
  }, [items, selectedItemId]);

  return (
    <Outlet
      context={{
        ...review,
        projectId,
        me,
        sheetId,
        setSheetId,
        selectedItemId,
        selectItem,
      }}
    />
  );
}
