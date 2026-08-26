/* ============================================================
   router-base.test.jsx — pins why App.jsx uses HashRouter rather than
   BrowserRouter (see App.jsx's comment at the swap for the full
   reasoning: vite.config.js's base: "./", the GitHub Pages subpath
   deploy.yml publishes to, and the file:// demo/index.html build).

   BrowserRouter matches window.location.pathname verbatim. This test
   simulates the one property both broken distribution paths share —
   window.location.pathname is something other than exactly "/" — using
   history.pushState, which jsdom supports without triggering a real
   navigation. It does not attempt to simulate a file:// origin
   specifically (jsdom's handling of the file: scheme is unreliable
   enough that a test built on it would not be trustworthy), but the
   failure mode under a non-root pathname is the same mechanism GitHub
   Pages hits, and it is the mechanism HashRouter is immune to — HashRouter
   reads the URL fragment instead, which is untouched by either the
   serving subpath or the origin scheme.
   ============================================================ */

import { describe, expect, it, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { BrowserRouter, HashRouter, Routes } from "react-router-dom";
import { appRoutes } from "./routes.jsx";

const store = {
  me: async () => ({ id: "u1", name: "Dana Whitfield" }),
  listProjects: async () => [],
  subscribe: () => () => {},
};

const routeProps = { store, me: { id: "u1", name: "Dana Whitfield" }, onSignedOut: () => {} };

describe("router choice under a non-root pathname", () => {
  afterEach(() => {
    // Don't leak the simulated Pages subpath into later tests in this
    // file (or, if the test runner reuses this jsdom window, later files).
    window.history.pushState({}, "", "/");
  });

  it("HashRouter still resolves the app when window.location.pathname is a deploy subpath", async () => {
    // Mirrors what GitHub Pages actually serves this app at, per
    // deploy.yml + the README: /<repo-name>/, not /.
    window.history.pushState({}, "", "/takeoff-review/");

    render(
      <HashRouter>
        <Routes>{appRoutes(routeProps)}</Routes>
      </HashRouter>,
    );

    expect(await screen.findByRole("heading", { name: /projects/i })).toBeTruthy();
  });

  it("BrowserRouter, by contrast, 404s under the exact same pathname — this is the bug being avoided", async () => {
    window.history.pushState({}, "", "/takeoff-review/");

    render(
      <BrowserRouter>
        <Routes>{appRoutes(routeProps)}</Routes>
      </BrowserRouter>,
    );

    // Falls through to the catch-all route instead of matching
    // /projects, because BrowserRouter matches the pathname verbatim and
    // nothing here declares a basename for the Pages subpath.
    expect(await screen.findByRole("link", { name: /back to projects/i })).toBeTruthy();
  });
});
