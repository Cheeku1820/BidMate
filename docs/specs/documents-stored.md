# B1 — Documents stored — design

**Date:** 2026-09-15
**Status:** Approved for planning.
**Implements:** `docs/roadmap/full-webapp-plan.md` Phase B, first of four sub-projects. Order: **B1 documents stored → B2 engine behind the API with per-sheet jobs → B3 drawing behind the markers → B4 confirm-drawings write-back and metering.** Each stacks on the one before.
**Builds on:** the `fix/engine-sheet-fidelity` branch (this branch is stacked on it).

## 1. What this is for

Today the browser holds the `File` objects an estimator dropped (`src/lib/uploadedFiles.js`), posts them to the unauthenticated engine on `:8100`, and posts the resulting JSON to the API. A reload loses the files. A re-run after a note works only because the browser still has them. Nothing is stored anywhere. That is the single biggest structural gap between the prototype and a product (full plan §0.1, fact 1).

B1 closes the storage half: every uploaded file lands in object storage and a `documents` row, through the authenticated API, before anything reads it. The API **never opens a PDF** — it streams bytes, hashes them, records them. Opening an untrusted PDF is a parser-sandbox concern (`ROADMAP.md` §2.2) and belongs to the worker B2 introduces; the API process already carries a test proving it imports no engine code, and this design keeps PyMuPDF out of it for the same reason.

## 2. Storage

**MinIO**, S3-compatible, as a compose service from day one — local and production speak the same API. Bucket `bidmate-documents`, created by a one-shot init container on `docker compose up`. Credentials and endpoint come from settings (`config.py`): `blob_endpoint`, `blob_access_key`, `blob_secret_key`, `blob_bucket`, `blob_region`, with dev values in `docker-compose.yml` and placeholders in `api/.env.example`. Nothing secret is committed.

**`BlobStore`** (`api/app/documents/blobstore.py`) — the interface the rest of the code sees:

```python
class BlobStore(Protocol):
    def put(self, key: str, stream: BinaryIO, content_type: str, size: int) -> None: ...
    def open(self, key: str) -> BinaryIO: ...      # streaming read
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
```

One implementation, `S3BlobStore` on `boto3`, pointed at MinIO by settings; one `MemoryBlobStore` for tests. The interface exists so presigned direct-to-storage upload (§5) is a second path later, not a rewrite.

**Keys are tenant-scoped by construction:** `orgs/{org_id}/projects/{project_id}/documents/{document_id}.pdf`. No code path builds a key from anything but the caller's org and the project it owns.

## 3. The `documents` table

```python
class Document(Base):
    __tablename__ = "documents"
    id: UUID (pk)
    project_id: UUID -> projects.id, ondelete CASCADE, indexed
    filename: str(300)          # as uploaded, for display
    doc_type: str(20)           # "Drawings" | "Specifications" | "Addendum" | "Scope" | "Other"
    content_type: str(100)      # "application/pdf"
    size_bytes: int
    sha256: str(64)
    storage_key: str(300)
    status: str(20)             # B1: "uploaded". B2 adds "processing" | "processed" | "failed".
    error: text, default ""     # estimator-facing reason when status is "failed" (B2)
    uploaded_by: UUID -> users.id
    created_at: timestamptz
    UniqueConstraint(project_id, sha256)   # the within-project duplicate rule, enforced by the database too
```

Migration `0019_documents`, reversible. No `document_pages` yet — page count, dimensions, rotation and tier all require opening the file; they arrive with B2.

`doc_type` is the closed set screen C's dropdown already offers. `status` is a closed set too; B1 writes only `uploaded`.

## 4. Rules

**Duplicate.** The same `sha256` already recorded in *this project* → the upload is refused with `409` and the existing document's filename, so screen C can say "This appears to be the same file as *E-set.pdf*, uploaded earlier." The bytes are not stored twice. The unique constraint backs the check.

**Never across projects, never across orgs.** No lookup, no dedup, no shared blob ever crosses a project boundary. Two subcontractors bidding the same job upload the same GC set and neither can learn the other did. This is the cross-tenant decision `ROADMAP.md` lists as "decide before writing storage," made concrete: hashing is for duplicate detection within a project only.

**Unsupported.** Not a PDF by both extension and declared content type → refused with `415` and copy naming the file and what is accepted ("*notes.docx* isn't a PDF. Upload PDF drawings, specifications, addenda, and scope documents."). Decided without parsing.

**Corrupt, password-protected.** Cannot be decided without opening the file. B1 stores them as `uploaded`; B2's worker sets `failed` with the reason on first look, and screen C shows it then. B1's screen C copy for the *uploaded* state says "Uploaded" and nothing more — it does not claim the file was read.

**Size.** No limit in B1 beyond what the proxy allows; the largest file in the corpus is 96 MB and streams fine. A limit is a product decision for B4's metering.

**Org isolation.** Every document route loads the project through `router.load_project` (which already scopes to the caller's org); a document in another org is `404`, never `403` — its existence is not disclosed.

## 5. Endpoints

| Route | Does |
|---|---|
| `POST /api/projects/{id}/documents` | multipart; one file per request; streams to `BlobStore.put` with the SHA-256 computed in flight; records the row; returns `DocumentOut`. `409` duplicate, `415` unsupported. |
| `GET /api/projects/{id}/documents` | the project's documents, oldest first |
| `PATCH /api/documents/{id}` | `doc_type` only |
| `DELETE /api/documents/{id}` | blob then row; `204` |
| `GET /api/documents/{id}/content` | org-scoped streaming read; `Cache-Control: private, no-store` (the same policy `main.py` applies to evidence images — this is NDA'd content) |

Upload goes **through the API**, not by presigned URL: one authenticated path, no CORS to MinIO, no presigned-hostname mismatch between the browser and a compose service, and the hash is computed where the row is written. Presigned direct-to-storage is the follow-up when sets outgrow streaming; `BlobStore` is what makes it a second `put` path rather than a redesign.

**Audit.** Upload and delete are recorded through `actions.commit()` — `kind="document_add"` / `"document_delete"`, `label` in the estimator's words ("Uploaded *E-set.pdf* as Drawings" / "Removed *E-set.pdf*"), `before`/`after` carrying the row's fields, never bytes. Like notes, these are audited and **not undoable**: undo covers takeoff items, and a deleted blob cannot be restored by replaying a row. The client's confirmation dialog (spec §6 requires confirmation before deleting a source document) is what stands in for undo.

## 6. The client

**`uploadedFiles.js` is deleted.** Screen C (`UploadDocuments.jsx`) becomes a view onto the API:

- The list is `GET …/documents`, so a reload shows the files still there.
- Each drop becomes one `POST` per file with an `XMLHttpRequest` so `upload.onprogress` drives the per-file progress bar; the row shows *Uploading… 42%* → *Uploaded*.
- The type dropdown `PATCH`es; remove opens the existing confirmation and `DELETE`s.
- Duplicate and unsupported responses render inline on the file row with the API's copy; the file is not listed.
- The "Review detected drawings" primary action needs at least one `Drawings` document.

**The interim engine path.** Until B2, the browser still runs the engine on `:8100`. `ProcessingStatus.jsx` stops reading `getUploadedFiles()` and instead fetches each document's bytes from `GET /documents/{id}/content` and posts them to the engine exactly as today. Reload-safe, and deleted by B2 together with `engineClient.js`. The same change applies to the notes re-run (`ApplyNotesBanner` → reprocess), which today also depends on browser-held files.

## 7. Copy

Every new estimator-facing string is sentence case, no "please" / "successfully" / exclamation marks, no internals — "object storage", "hash", "S3", "bucket" never appear in the interface. Error copy names the file and the recovery: what is accepted, or which earlier upload it duplicates.

## 8. Testing

- **`BlobStore`**: `MemoryBlobStore` round-trip; `S3BlobStore` put/open/delete/exists against MinIO, skipped with a printed reason when `blob_endpoint` isn't reachable — CI gets a MinIO service container so it runs there.
- **Upload**: stores bytes and a row with the right key shape, size and hash; a second identical upload to the same project → `409` naming the first; the same bytes to a *different* project → stored again with a different key (no cross-project dedup); `.docx` → `415`, nothing stored.
- **Isolation**: org B's user requesting org A's document → `404`; listing org A's project → `404`.
- **Delete**: blob gone, row gone, an action recorded with the label; the action is not on the undo stack.
- **Content**: streams the exact bytes back with `no-store`.
- **Audit**: `document_add` recorded with filename and type in `after`, no bytes.
- **Client**: screen C lists persisted documents on mount; progress renders from XHR events; duplicate and unsupported copy appear on the row; delete asks first; `uploadedFiles.js` is gone (`grep` finds no importer); processing fetches bytes from the API.
- **Boundary**: `test_api_import_boundary.py` still passes — `boto3` is allowed, `pymupdf` and `app.engine` still are not.

## 9. Out of scope, named

- Opening any PDF in the API — page count, dimensions, rotation, tier, encryption, corruption → B2.
- Presigned / resumable / multipart upload.
- Retention, lifecycle, tiering.
- Malware scanning.
- A size limit.
- `document_pages`.
- Revision sets (which upload supersedes which) — `Sheet.superseded_at` exists and stays unset; Phase F.

## 10. Dependencies

`boto3` added to `api/requirements.txt`; a `minio` service and a `minio-init` one-shot in `docker-compose.yml`; MinIO service container in `.github/workflows/ci.yml`.
