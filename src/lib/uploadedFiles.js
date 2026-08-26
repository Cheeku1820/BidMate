/* ============================================================
   uploadedFiles.js — a tiny in-memory holder for the File objects an
   estimator dropped on the upload screen, keyed by project id.

   File objects can't be serialized into the store or router state
   cleanly, so this module-level map carries them from the upload screen
   to the processing screen within the session. It is deliberately not
   persisted: a page reload loses the pending upload, which is honest for
   a client-only demo (a real backend would have stored the file).
   ============================================================ */

const uploads = new Map(); // projectId -> [{ file, docType }]

export function setUploadedFiles(projectId, files) {
  uploads.set(projectId, files);
}

export function getUploadedFiles(projectId) {
  return uploads.get(projectId) || [];
}

export function clearUploadedFiles(projectId) {
  uploads.delete(projectId);
}
