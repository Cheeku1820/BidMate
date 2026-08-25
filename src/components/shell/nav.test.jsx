/* ============================================================
   nav.test.jsx — the two navigation components, tested together on
   purpose.

   Both were changed by the same review findings, and the fixes only work
   if they stay identical: a disabled destination in either nav has to
   carry an accessible name that survives, and the two navs must not
   drift into different treatments of the same idea. A file per component
   would let them drift without anything failing, which is exactly what
   happened before these fixes existed.

   What is pinned here, and why each would otherwise regress silently:

   - Disabled items announce their own name. `aria-label` on a bare
     <span> with no ARIA role is commonly dropped by assistive
     technology, so before the fix the five disabled company destinations
     announced as nothing at all once the nav was collapsed. `role="link"`
     is what gives the label somewhere to attach.
   - Disabled items stay out of the tab order and read as unavailable
     rather than actionable.
   - The two navs use the same treatment, asserted by comparing them
     rather than by trusting two separate lists of expectations.
   - CompanyNav collapses on the takeoff route. That is not cosmetic: it
     is the fix for spec §12's "the blueprint stays the largest element"
     at the 1024px floor the README claims support for. Nothing else in
     the suite covers it.
   ============================================================ */

import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import CompanyNav from "./CompanyNav.jsx";
import ProjectNav from "./ProjectNav.jsx";

const renderCompanyNav = (path = "/projects") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <CompanyNav />
    </MemoryRouter>,
  );

const renderProjectNav = () =>
  render(
    <MemoryRouter initialEntries={["/projects/p1"]}>
      <ProjectNav projectId="p1" />
    </MemoryRouter>,
  );

/** Every element the nav renders as a disabled destination. */
const disabledItems = (nav) =>
  within(nav)
    .getAllByRole("link")
    .filter((el) => el.getAttribute("aria-disabled") === "true");

describe("CompanyNav", () => {
  it("shows every spec §4.1 destination, built or not", () => {
    renderCompanyNav();
    for (const label of [
      /projects/i,
      /accuracy/i,
      /company library/i,
      /integrations/i,
      /company settings/i,
      /help/i,
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }
  });

  it("gives unbuilt destinations a name that survives, and keeps them unreachable", () => {
    renderCompanyNav();
    const nav = screen.getByRole("navigation", { name: /main/i });
    const disabled = disabledItems(nav);

    // Five of six: only Projects is built.
    expect(disabled).toHaveLength(5);

    for (const item of disabled) {
      // A bare span with aria-label announces as nothing; role="link" is
      // what makes the name stick.
      expect(item.tagName).toBe("SPAN");
      expect(item.getAttribute("role")).toBe("link");
      expect(item.getAttribute("tabIndex")).toBe("-1");
      expect(item).not.toHaveAttribute("href");
      // The name must identify *which* destination, not a shared phrase.
      expect(item.getAttribute("aria-label")).toMatch(/\S/);
    }

    // Each disabled item names a different destination.
    const names = disabled.map((el) => el.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(names.length);
  });

  it("keeps those names when collapsed, which is when the visible text is gone", async () => {
    renderCompanyNav();
    const nav = screen.getByRole("navigation", { name: /main/i });

    const before = disabledItems(nav).map((el) => el.getAttribute("aria-label"));
    await userEvent.click(screen.getByRole("button", { name: /collapse navigation/i }));

    // Visible label text is gone...
    expect(within(nav).queryByText("Accuracy")).toBeNull();
    // ...but the accessible names are unchanged.
    expect(disabledItems(nav).map((el) => el.getAttribute("aria-label"))).toEqual(before);
    expect(screen.getByRole("link", { name: /accuracy/i })).toBeTruthy();
  });

  it("starts expanded away from the takeoff route", () => {
    renderCompanyNav("/projects");
    expect(screen.getByRole("button", { name: /collapse navigation/i })).toBeTruthy();
    expect(screen.getByText("BidMate")).toBeTruthy();
  });

  it("starts collapsed on the takeoff route, so the blueprint keeps its width", () => {
    // Spec §12: the blueprint is the largest element in the review
    // workspace. At 1024px the nav's expanded width pushed the canvas
    // narrower than the detail panel beside it.
    renderCompanyNav("/projects/p1/takeoff");
    expect(screen.getByRole("button", { name: /expand navigation/i })).toBeTruthy();
    expect(screen.queryByText("BidMate")).toBeNull();
  });

  it("lets the estimator override the collapse in either direction", async () => {
    renderCompanyNav("/projects/p1/takeoff");
    await userEvent.click(screen.getByRole("button", { name: /expand navigation/i }));
    expect(screen.getByText("BidMate")).toBeTruthy();
    expect(screen.getByRole("button", { name: /collapse navigation/i })).toBeTruthy();
  });
});

describe("ProjectNav", () => {
  it("lists all thirteen spec §4.2 workspaces, so the workflow's shape stays visible", () => {
    renderProjectNav();
    const nav = screen.getByRole("navigation", { name: /project workspaces/i });
    expect(within(nav).getAllByRole("link")).toHaveLength(13);
  });

  it("links only the built workspaces and disables the rest by name", () => {
    renderProjectNav();
    const nav = screen.getByRole("navigation", { name: /project workspaces/i });

    expect(within(nav).getByRole("link", { name: /^overview/i })).toHaveAttribute("href", "/projects/p1");
    expect(within(nav).getByRole("link", { name: /^blueprint takeoff/i })).toHaveAttribute(
      "href",
      "/projects/p1/takeoff",
    );

    expect(within(nav).getByRole("link", { name: /^documents/i })).toHaveAttribute("href", "/projects/p1/documents");
    expect(within(nav).getByRole("link", { name: /^export/i })).toHaveAttribute("href", "/projects/p1/export");

    const disabled = disabledItems(nav);
    // 13 workspaces total, minus the five now built: overview, blueprint
    // takeoff, takeoff spreadsheet, documents (intake), and export.
    expect(disabled).toHaveLength(8);
    const names = disabled.map((el) => el.getAttribute("aria-label"));
    expect(new Set(names).size).toBe(names.length);
  });
});

describe("the two navs", () => {
  it("treat an unavailable destination identically", () => {
    // Asserted by comparison rather than by two separate expectation
    // lists: the point of the finding was that the navs must not drift,
    // and two lists can be updated independently without anything
    // failing.
    const company = renderCompanyNav();
    const companyItem = disabledItems(
      within(company.container).getByRole("navigation", { name: /main/i }),
    )[0];
    const companyShape = {
      tag: companyItem.tagName,
      role: companyItem.getAttribute("role"),
      ariaDisabled: companyItem.getAttribute("aria-disabled"),
      tabIndex: companyItem.getAttribute("tabIndex"),
      hasHref: companyItem.hasAttribute("href"),
      unavailableClass: companyItem.className.includes("is-unavailable"),
      labelSuffix: companyItem.getAttribute("aria-label").replace(/^.*?—/, "").trim(),
    };
    company.unmount();

    const project = renderProjectNav();
    const projectItem = disabledItems(
      within(project.container).getByRole("navigation", { name: /project workspaces/i }),
    )[0];
    const projectShape = {
      tag: projectItem.tagName,
      role: projectItem.getAttribute("role"),
      ariaDisabled: projectItem.getAttribute("aria-disabled"),
      tabIndex: projectItem.getAttribute("tabIndex"),
      hasHref: projectItem.hasAttribute("href"),
      unavailableClass: projectItem.className.includes("is-unavailable"),
      labelSuffix: projectItem.getAttribute("aria-label").replace(/^.*?—/, "").trim(),
    };

    expect(projectShape).toEqual(companyShape);
  });
});
