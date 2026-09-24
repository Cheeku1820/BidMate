/* ============================================================
   applyProposal.js — the one map from a proposal's kind to the call
   that applies it.

   Every entry is the endpoint the record's own form already uses, so
   the panel is one more caller of the structured interface: undo,
   audit and sync behave exactly as they do for a hand edit, because it
   is the hand edit's path. Nothing else in the panel knows an endpoint.

   An item is applied with approve: false, always. The panel proposes;
   approving is the estimator's own act, taken where the evidence is.

   store.applyProposal takes THREE positional arguments — (itemId,
   proposal, { approve, note }), see src/lib/store/api.js — rather than
   the two-argument, single-wrapped-object call an earlier sketch of
   this map assumed. This dispatch follows the real store.
   ============================================================ */

export async function applyProposal(store, projectId, proposal) {
  switch (proposal.kind) {
    case "item":
      return store.applyProposal(proposal.itemId, proposal.proposal, { approve: false, note: null });
    case "note":
      return store.createNote(projectId, {
        scope: "project", scopeRef: null, title: proposal.title, body: proposal.body,
        category: proposal.category, status: "open", rfiNeeded: false, usage: "context",
        sourceRef: "", obsoleteAfterRevision: "",
      });
    case "scope":
      return store.decideScope(proposal.statementId,
        proposal.status ? { status: proposal.status } : { editedText: proposal.editedText });
    case "plan_line":
      return store.decidePlanLine(projectId, proposal.key,
        proposal.status ? { status: proposal.status } : { editedText: proposal.editedText });
    case "plan_answer":
      return store.answerPlanQuestion(projectId, proposal.key, proposal.body);
    default:
      throw { code: "not_applicable", message: "There's nothing to apply here." };
  }
}
