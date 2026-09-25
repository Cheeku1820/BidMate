import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import MatchResultCard from "./MatchResultCard.jsx";

const found = (n) => ({ id: "m1", status: "found", box: [100, 100, 20, 10], count: n, matches: Array.from({ length: n }, (_, i) => [100 + i * 50, 100, 20, 10]), error: "" });
const pending = () => ({ id: "m1", status: "pending", box: [100, 100, 20, 10], count: 0, matches: [], error: "" });

describe("MatchResultCard", () => {
  it("shows the count and adds with a name", () => {
    const onAccept = vi.fn();
    render(<MatchResultCard match={found(3)} onAccept={onAccept} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByText("3 matches found")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Duplex receptacle" } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3 to the takeoff" }));
    expect(onAccept).toHaveBeenCalledWith({ name: "Duplex receptacle", symbol: expect.any(String), system: expect.any(String) });
  });

  it("not sure yet files it without a name", () => {
    const onAccept = vi.fn();
    render(<MatchResultCard match={found(3)} onAccept={onAccept} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    fireEvent.click(screen.getByRole("button", { name: "Not sure yet" }));
    expect(onAccept).toHaveBeenCalledWith({ notSure: true });
  });

  it("the add button is disabled without a name", () => {
    render(<MatchResultCard match={found(3)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByRole("button", { name: "Add 3 to the takeoff" }).disabled).toBe(true);
  });

  it("offers the boxed one alone when nothing else matched", () => {
    render(<MatchResultCard match={found(1)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByText("No other symbols like this were found")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add 1 to the takeoff" })).toBeTruthy();
  });

  it("offers only a retry and discard when nothing at all was found", () => {
    const onRetry = vi.fn();
    render(<MatchResultCard match={found(0)} onAccept={() => {}} onDiscard={() => {}} onRetry={onRetry} sheetNumber="E2.1" />);
    expect(screen.getByRole("heading", { name: "No symbols like this were found" })).toBeTruthy();
    expect(screen.getByText("Draw the box more tightly around one symbol and try again.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Add/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Not sure yet" })).toBeNull();
    expect(screen.queryByLabelText("Name")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeTruthy();
  });

  it("shows the failure copy and a retry", () => {
    const onRetry = vi.fn();
    render(<MatchResultCard match={{ ...found(0), status: "failed", error: "The symbol couldn't be searched for on this sheet." }} onAccept={() => {}} onDiscard={() => {}} onRetry={onRetry} sheetNumber="E2.1" />);
    expect(screen.getByText(/couldn't be searched/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it("never shows a percentage or an AI word", () => {
    const { container } = render(<MatchResultCard match={found(3)} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(container.textContent).not.toMatch(/%|\bAI\b|confidence/i);
  });

  it("shows the refusal error on a found match, above the buttons", () => {
    render(<MatchResultCard match={{ ...found(3), error: "That name is already used by a different symbol on this sheet." }} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByText("That name is already used by a different symbol on this sheet.")).toBeTruthy();
  });

  it("pre-fills the name from the legend suggestion and enables Add", () => {
    render(<MatchResultCard match={{ ...found(3), suggestedName: "Duplex receptacle" }} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />);
    expect(screen.getByLabelText("Name").value).toBe("Duplex receptacle");
    expect(screen.getByRole("button", { name: "Add 3 to the takeoff" }).disabled).toBe(false);
  });

  it("picks up the legend suggestion when the poll resolves a pending search, not just on a fresh mount", () => {
    const { rerender } = render(
      <MatchResultCard match={pending()} onAccept={() => {}} onDiscard={() => {}} onRetry={() => {}} sheetNumber="E2.1" />
    );
    // The same component instance the app actually keeps mounted: the
    // pending search resolves and useReviewStore's poll hands the card
    // an updated match with the same id, not a remount.
    rerender(
      <MatchResultCard
        match={{ ...found(3), id: "m1", suggestedName: "Duplex receptacle" }}
        onAccept={() => {}}
        onDiscard={() => {}}
        onRetry={() => {}}
        sheetNumber="E2.1"
      />
    );
    expect(screen.getByLabelText("Name").value).toBe("Duplex receptacle");
    expect(screen.getByRole("button", { name: "Add 3 to the takeoff" }).disabled).toBe(false);
  });

  it("does not clobber a name the estimator already typed once the card is in its found state", () => {
    const { rerender } = render(
      <MatchResultCard
        match={{ ...found(3), suggestedName: "Duplex receptacle" }}
        onAccept={() => {}}
        onDiscard={() => {}}
        onRetry={() => {}}
        sheetNumber="E2.1"
      />
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Custom name" } });
    // A later poll tick hands down the same match (same suggestedName) --
    // must not stomp what the estimator is typing.
    rerender(
      <MatchResultCard
        match={{ ...found(3), suggestedName: "Duplex receptacle" }}
        onAccept={() => {}}
        onDiscard={() => {}}
        onRetry={() => {}}
        sheetNumber="E2.1"
      />
    );
    expect(screen.getByLabelText("Name").value).toBe("Custom name");
  });
});
