/* ============================================================
   settingsStore.test.js — the company-default -> project-override
   resolution chain (spec §5 J/K, §6).

   The rule that matters: a project value is either its company default or
   an explicit override, and restoring an override returns it to the
   default. Every screen reads this through resolveProject rather than
   re-deriving it, so this is where the chain is pinned.
   ============================================================ */

import { beforeEach, describe, expect, it } from "vitest";
import {
  COMPANY_DEFAULTS,
  getCompanySettings,
  setCompanyValue,
  resolveProject,
  setProjectOverride,
  restoreCompanyDefault,
} from "./settingsStore.js";

beforeEach(() => localStorage.clear());

describe("company settings", () => {
  it("returns the defaults when nothing has been edited", () => {
    const settings = getCompanySettings();
    expect(settings.journeymanRate.value).toBe(COMPANY_DEFAULTS.journeymanRate.value);
  });

  it("persists an edited value with a fresh updated date", () => {
    setCompanyValue("journeymanRate", 75);
    expect(getCompanySettings().journeymanRate.value).toBe(75);
  });
});

describe("project resolution chain", () => {
  it("resolves to the company default until a field is overridden", () => {
    const resolved = resolveProject("p1");
    expect(resolved.wastePercent.value).toBe(COMPANY_DEFAULTS.wastePercent.value);
    expect(resolved.wastePercent.overridden).toBe(false);
    expect(resolved.wastePercent.source).toBe("Company default");
  });

  it("reports an override as such, carrying the company value for restore", () => {
    setProjectOverride("p1", "wastePercent", 5);
    const resolved = resolveProject("p1");
    expect(resolved.wastePercent.value).toBe(5);
    expect(resolved.wastePercent.overridden).toBe(true);
    expect(resolved.wastePercent.source).toBe("Project override");
    expect(resolved.wastePercent.companyValue).toBe(COMPANY_DEFAULTS.wastePercent.value);
  });

  it("restores an override back to the company default", () => {
    setProjectOverride("p1", "wastePercent", 5);
    restoreCompanyDefault("p1", "wastePercent");
    const resolved = resolveProject("p1");
    expect(resolved.wastePercent.value).toBe(COMPANY_DEFAULTS.wastePercent.value);
    expect(resolved.wastePercent.overridden).toBe(false);
  });

  it("keeps overrides scoped to their own project", () => {
    setProjectOverride("p1", "profitPercent", 20);
    expect(resolveProject("p2").profitPercent.overridden).toBe(false);
    expect(resolveProject("p2").profitPercent.value).toBe(COMPANY_DEFAULTS.profitPercent.value);
  });
});
