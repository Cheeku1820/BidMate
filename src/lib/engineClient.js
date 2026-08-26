/* ============================================================
   engineClient.js — calls the standalone estimate service
   (api/estimate_service.py) that runs the takeoff engine.

   Kept separate from the store: the store owns the reviewable takeoff;
   this just fetches the engine's raw payload for the processing screen to
   ingest. Errors are turned into estimator-readable messages (the most
   common one being "the service isn't running").
   ============================================================ */

const BASE = "http://localhost:8100";

/** POST a drawing PDF + location to /estimate/full, returning the
 *  per-sheet takeoff payload. Throws an Error with a readable message. */
export async function estimateFull(file, location) {
  const form = new FormData();
  form.append("location", location || "");
  form.append("file", file);

  let res;
  try {
    res = await fetch(`${BASE}/estimate/full`, { method: "POST", body: form });
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
  if (!res.ok) throw new Error(data.error || "The takeoff couldn't be produced from these drawings.");
  return data;
}
