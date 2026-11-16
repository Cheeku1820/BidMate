import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import TakeoffSpreadsheet from "./TakeoffSpreadsheet.jsx";
import { ConversationScreenProvider, useConversationScreenContext } from "../conversation/screenContext.jsx";

const items = [
  { id: "i1", sheetId: "s1", name: "20A duplex receptacle", description: "Duplex, 20A", system: "Power", quantity: 12, unit: "ea", status: "approved", notes: "", rejected: false, warnings: [], version: 1 },
  { id: "i2", sheetId: "s2", name: "High bay fixture", description: "LED high bay", system: "Lighting", quantity: 4, unit: "ea", status: "attention", notes: "", rejected: false, warnings: [{ title: "Schedule conflict" }], version: 1 },
  { id: "i3", sheetId: "s1", name: "Conduit run", description: "3/4in EMT", system: "Power", quantity: 60, unit: "ft", status: "missing", notes: "", rejected: false, warnings: [], version: 1 },
];

const context = {
  snapshot: {
    sheets: [
      { id: "s1", number: "E1.1", title: "Level 1 power", superseded: false },
      { id: "s2", number: "E2.1", title: "Warehouse power", superseded: false },
    ],
    items,
    totals: { bySystem: {}, approvedCount: 1, remainingCount: 2, attentionCount: 1, missingCount: 1, approvedUnits: 12 },
    undo: { canUndo: false, canRedo: false, label: null, undoBy: null },
    presence: [],
  },
  loading: false,
  loadError: null,
  selectedItemId: null,
  selectItem: vi.fn(),
  sheetId: "s1",
  setSheetId: vi.fn(),
  bulkApprove: vi.fn(),
  projectId: "p1",
};

vi.mock("../project/useWorkspaceContext.js", () => ({
  useWorkspaceContext: () => context,
}));

const renderSheet = () =>
  render(
    <MemoryRouter>
      <TakeoffSpreadsheet />
    </MemoryRouter>,
  );

/** Renders what the conversation screen context has for the current view. */
function ViewProbe() {
  const { view } = useConversationScreenContext();
  return <p data-testid="view">{JSON.stringify(view)}</p>;
}

const renderSheetWithConversation = () =>
  render(
    <ConversationScreenProvider>
      <ViewProbe />
      <MemoryRouter>
        <TakeoffSpreadsheet />
      </MemoryRouter>
    </ConversationScreenProvider>,
  );

describe("TakeoffSpreadsheet", () => {
  it("renders one row per item with proper table semantics", () => {
    renderSheet();
    expect(screen.getAllByRole("row")).toHaveLength(items.length + 1); // + header
    expect(screen.getByRole("columnheader", { name: /status/i })).toBeTruthy();
  });

  it("shows each status as text, not colour alone", () => {
    renderSheet();
    expect(screen.getByText(/estimator approved/i)).toBeTruthy();
    expect(screen.getByText(/needs attention/i)).toBeTruthy();
    expect(screen.getByText(/missing information/i)).toBeTruthy();
  });

  it("does not render columns that have no data behind them", () => {
    // See the plan's Data Reality section: a blank "Waste factor" column
    // reads as "no waste applied", which is a fabricated fact.
    renderSheet();
    for (const absent of [/waste/i, /manufacturer/i, /floor/i, /specification/i]) {
      expect(screen.queryByRole("columnheader", { name: absent })).toBeNull();
    }
  });

  it("filters by status", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("20A duplex receptacle")).toBeNull();
  });

  it("searches across item name and description", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "high bay");
    expect(screen.getByText("High bay fixture")).toBeTruthy();
    expect(screen.queryByText("Conduit run")).toBeNull();
  });

  it("sorts by a column when its header is activated", async () => {
    renderSheet();
    await userEvent.click(screen.getByRole("button", { name: /sort by item/i }));
    // The item name lives in the row's <th scope="row"> (WCAG 2.2 AA),
    // which carries role "rowheader" rather than "cell" -- read it
    // there rather than by cell index, which the rowheader doesn't
    // occupy a slot in.
    const names = screen.getAllByRole("row").slice(1).map((r) => within(r).getByRole("rowheader").textContent);
    expect(names).toEqual([...names].sort());
  });

  it("hides a column without removing its rows", async () => {
    // Column visibility filters what is drawn, never what is counted --
    // the same rule the canvas layer toggles follow.
    renderSheet();
    const before = screen.getAllByRole("row").length;

    await userEvent.click(screen.getByRole("button", { name: /columns/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /system/i }));

    expect(screen.queryByRole("columnheader", { name: /^system$/i })).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(before);
  });

  it("names a recovery action when nothing matches", async () => {
    renderSheet();
    await userEvent.type(screen.getByLabelText(/search items/i), "zzzz");
    expect(screen.getByText(/no items match/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /clear search/i })).toBeTruthy();
  });

  it("reports its status filter and search to the conversation context", async () => {
    renderSheetWithConversation();
    await userEvent.click(screen.getByRole("button", { name: /needs attention/i }));
    await userEvent.type(screen.getByLabelText(/search items/i), "LP-2");

    await waitFor(() => {
      expect(JSON.parse(screen.getByTestId("view").textContent)).toEqual({ filter: "attention", search: "LP-2" });
    });
  });
});


/* --- docs/plans/estimate-without-asking.md Task 12 -------------------
   A guessed line that lands invisibly is worthless, so the row has to
   say "Guessed" and show its confidence. The hard rule here is that
   "Guessed" is NOT a fifth review label: it rides the counted/assumed
   axis, the row's own status stays `ready`, and the four labels keep
   their meanings and their colours. */

describe("a guessed row", () => {
  const guessed = {
    id: "i9", sheetId: "s2", name: "Allowance — unidentified devices on E2.1",
    description: "", system: "Power", quantity: 1, unit: "ls", status: "ready",
    notes: "", rejected: false, warnings: [], version: 1,
    origin: "assumed", confidence: 5,
    confidenceReasons: ["Counted off the drawing, but nothing named what these are"],
    materialCost: 1200, laborHours: 4, totalCost: 1500,
  };

  it("marks a guessed row guessed, and not with a review label", async () => {
    context.snapshot.items = [guessed];
    renderSheet();
    expect(await screen.findByText("Guessed")).toBeInTheDocument();
    expect(screen.queryByText("Needs attention")).not.toBeInTheDocument();
  });

  it("still shows the row's real review status beside it", async () => {
    /* Two independent channels. The guess tag says where the number
       came from; the Pill says what a person has done about it. */
    context.snapshot.items = [guessed];
    renderSheet();
    expect(await screen.findByText("Guessed")).toBeInTheDocument();
    expect(screen.getByText("Ready to review")).toBeInTheDocument();
  });

  it("names the sheet its evidence sits on", async () => {
    /* A guessed line has no marker and no evidence crop — nothing was
       read. The sheet it is attached to is the thing an estimator opens
       to check it, so the row must name it. */
    context.snapshot.items = [guessed];
    renderSheet();
    const row = (await screen.findByText("Guessed")).closest("tr");
    expect(within(row).getByText("E2.1")).toBeInTheDocument();
  });

  it("shows the confidence meter with its reasons", async () => {
    context.snapshot.items = [guessed];
    renderSheet();
    const row = (await screen.findByText("Guessed")).closest("tr");
    expect(within(row).getByRole("img")).toHaveAccessibleName(/5 out of 10/i);
    expect(within(row).getByRole("img")).toHaveAccessibleName(/nothing named what these are/i);
  });

  it("marks a counted row counted", async () => {
    context.snapshot.items = [items[0]];
    renderSheet();
    expect(await screen.findByText("Counted")).toBeInTheDocument();
  });

  it("leaves the meter empty for a row that was never scored", async () => {
    /* Review focus 5. An item from before the column exists renders an
       empty bar rather than a 1, and nothing throws. */
    context.snapshot.items = [items[0]];
    renderSheet();
    const row = (await screen.findByText("Counted")).closest("tr");
    expect(within(row).getByRole("img")).toHaveAccessibleName(/not scored/i);
  });

  it("cannot be bulk approved, because only Ready to review items can", async () => {
    /* CLAUDE.md: bulk approval applies only to Ready to review. A
       guessed line IS ready, so this is a check that the guess tag did
       not quietly change that — approval still means a person looked. */
    context.snapshot.items = [guessed];
    renderSheet();
    expect(await screen.findByText("Guessed")).toBeInTheDocument();
    expect(screen.getByText("Ready to review")).toBeInTheDocument();
  });
});

describe("sorting the confidence column", () => {
  /* Review finding 9, at the table level: the behaviour an estimator
     actually sees when they click the Confidence header. */
  const scored = (id, confidence) => ({
    id, sheetId: "s1", name: `Item ${id}`, description: "", system: "Power",
    quantity: 1, unit: "ea", status: "ready", notes: "", rejected: false,
    warnings: [], version: 1, origin: "counted", confidence,
    confidenceReasons: confidence ? ["Counted off the drawing"] : null,
  });

  const names = () =>
    Array.from(document.querySelectorAll("tbody th[scope=row]")).map((el) => el.textContent);

  it("puts an unscored row last ascending", async () => {
    context.snapshot.items = [scored("a", 3), scored("b", null), scored("c", 9)];
    renderSheet();
    await userEvent.click(await screen.findByRole("button", { name: /confidence/i }));
    expect(names()).toEqual(["Item a", "Item c", "Item b"]);
  });

  it("puts an unscored row last descending too", async () => {
    context.snapshot.items = [scored("a", 3), scored("b", null), scored("c", 9)];
    renderSheet();
    const header = await screen.findByRole("button", { name: /confidence/i });
    await userEvent.click(header);
    await userEvent.click(header);
    expect(names()).toEqual(["Item c", "Item a", "Item b"]);
  });

  it("orders scores as numbers, not as text", async () => {
    /* The string comparator put "10 of 10" before "3 of 10". */
    context.snapshot.items = [scored("a", 10), scored("b", 3)];
    renderSheet();
    await userEvent.click(await screen.findByRole("button", { name: /confidence/i }));
    expect(names()).toEqual(["Item b", "Item a"]);
  });
});
