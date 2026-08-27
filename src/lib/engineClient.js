/* ============================================================
   engineClient.js — calls the standalone estimate service
   (api/estimate_service.py) that runs the takeoff engine.

   Kept separate from the store: the store owns the reviewable takeoff;
   this just fetches the engine's raw payload for the processing screen to
   ingest. Errors are turned into estimator-readable messages (the most
   common one being "the service isn't running").
   ============================================================ */

const BASE = "http://localhost:8100";

async function post(path, form) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method: "POST", body: form });
  } catch {
    throw new Error(
      "Couldn't reach the estimate service. Start it in the api folder with: uvicorn estimate_service:app --port 8100",
    );
  }
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error("The estimate service returned an unexpected response.");
  }
  if (!res.ok) throw new Error(data.error || "The takeoff couldn't be produced from these documents.");
  return data;
}

/** POST a single drawing PDF + location to /estimate/full (used by the
 *  Instant estimate page). */
export async function estimateFull(file, location) {
  const form = new FormData();
  form.append("location", location || "");
  form.append("file", file);
  return post("/estimate/full", form);
}

/** Peek at a document's content to refine its type when the filename
 *  wasn't informative. Returns a DOC_TYPE string or null — null (including
 *  when the service is down) means "keep the filename guess". Best-effort,
 *  never throws. */
export async function classifyDoc(file) {
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch(`${BASE}/classify`, { method: "POST", body: form });
    if (!res.ok) return null;
    const data = await res.json();
    return data.type || null;
  } catch {
    return null;
  }
}

/** POST the whole document set (each `{ file, docType }`) + location to
 *  /estimate/project: Drawings run the pipeline, everything else is read
 *  as context. Returns the merged per-sheet takeoff payload. */
export async function estimateProject(uploaded, location) {
  const form = new FormData();
  form.append("location", location || "");
  for (const { file, docType } of uploaded) {
    form.append("files", file);
    form.append("types", docType || "Other");
  }
  return post("/estimate/project", form);
}
