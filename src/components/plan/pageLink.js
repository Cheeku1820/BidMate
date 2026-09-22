/* The page a plan line came from, as the document's own content at
   that page. The API streams the stored file (documents/router.py
   get_content) and the session cookie carries auth, so a plain link
   works and the browser's viewer opens at the fragment's page. */

export function documentPageHref(documentId, page) {
  if (!documentId) return "";
  const base = `/api/documents/${documentId}/content`;
  return page ? `${base}#page=${page}` : base;
}
