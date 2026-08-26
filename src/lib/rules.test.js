/* ============================================================
   rules.test.js — direct coverage for rules.js functions that
   contract.test.js exercises only indirectly (or not at all).

   approvableInBulk has no caller yet — src/lib/store/seed.js has no
   bulkApprove method this task (design doc, "its consumer is screen G,
   which is a later slice") — so nothing in contract.test.js reaches it.
   CLAUDE.md names this exact rule as easy to break by accident ("Bulk
   approval applies only to Ready to review items. Never to Needs
   attention or Missing information, no matter how convenient it
   looks"), so it gets a direct test rather than waiting for screen G to
   discover a sign inversion.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { approvableInBulk } from "./rules.js";

describe("approvableInBulk", () => {
  it("accepts only Ready to review items that are not rejected", () => {
    const items = [
      { id: "ready-and-live", status: "ready", rejected: false },
      // A rejected item stays out even when its status is "ready" --
      // rejection and status are independent fields (task-15-report.md,
      // "rejected is a flag, not a fifth status"), and the convenient-
      // looking shortcut of "status ready is enough" is exactly the
      // sign inversion CLAUDE.md warns about.
      { id: "ready-but-rejected", status: "ready", rejected: true },
      { id: "attention", status: "attention", rejected: false },
      { id: "missing", status: "missing", rejected: false },
      { id: "approved", status: "approved", rejected: false },
    ];

    const result = approvableInBulk(items).map((i) => i.id);

    expect(result).toEqual(["ready-and-live"]);
  });
});
