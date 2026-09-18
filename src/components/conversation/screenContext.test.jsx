import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import {
  ConversationScreenProvider,
  SCREEN_NAMES,
  screenNameFromPath,
  useConversationScreenContext,
  useConversationSelection,
  useConversationView,
} from "./screenContext.jsx";
import { exampleQuestions } from "./exampleQuestions.js";

describe("screenNameFromPath", () => {
  it("names every project route from the closed set", () => {
    expect(SCREEN_NAMES).toEqual([
      "overview", "documents", "confirm", "processing", "takeoff", "spreadsheet",
      "notes", "labor", "pricing", "export", "settings",
    ]);
    expect(screenNameFromPath("/projects/p1")).toBe("overview");
    expect(screenNameFromPath("/projects/p1/documents")).toBe("documents");
    expect(screenNameFromPath("/projects/p1/documents/confirm")).toBe("confirm");
    expect(screenNameFromPath("/projects/p1/processing")).toBe("processing");
    expect(screenNameFromPath("/projects/p1/takeoff")).toBe("takeoff");
    expect(screenNameFromPath("/projects/p1/spreadsheet")).toBe("spreadsheet");
    expect(screenNameFromPath("/projects/p1/notes")).toBe("notes");
    expect(screenNameFromPath("/projects/p1/labor")).toBe("labor");
    expect(screenNameFromPath("/projects/p1/pricing")).toBe("pricing");
    expect(screenNameFromPath("/projects/p1/export")).toBe("export");
    expect(screenNameFromPath("/projects/p1/settings")).toBe("settings");
  });

  it("is null off a project and for /projects/new", () => {
    expect(screenNameFromPath("/projects")).toBeNull();
    expect(screenNameFromPath("/projects/new")).toBeNull();
    expect(screenNameFromPath("/settings")).toBeNull();
  });
});

function Reader() {
  const { selection, view } = useConversationScreenContext();
  return <p>{JSON.stringify({ selection, view })}</p>;
}

function Reporter({ selection, view }) {
  useConversationSelection(selection);
  useConversationView(view);
  return null;
}

describe("the reporting hooks", () => {
  it("publish and clear on unmount", () => {
    const { rerender } = render(
      <ConversationScreenProvider>
        <Reporter selection={{ sheetId: "s1", sheetLabel: "E2.1", itemId: null, itemLabel: null }} view={{ filter: "attention", search: "" }} />
        <Reader />
      </ConversationScreenProvider>,
    );
    expect(screen.getByText(/"sheetLabel":"E2.1"/)).toBeTruthy();
    expect(screen.getByText(/"filter":"attention"/)).toBeTruthy();

    rerender(
      <ConversationScreenProvider>
        <Reader />
      </ConversationScreenProvider>,
    );
    expect(screen.getByText('{"selection":{},"view":{}}')).toBeTruthy();
  });

  it("gives safe defaults without a provider", () => {
    render(<Reader />);
    expect(screen.getByText('{"selection":{},"view":{}}')).toBeTruthy();
  });
});

describe("exampleQuestions", () => {
  it("has three per screen and none for null", () => {
    for (const name of SCREEN_NAMES) expect(exampleQuestions(name)).toHaveLength(3);
    expect(exampleQuestions(null)).toEqual([]);
  });
});
