import { describe, expect, test } from "vitest";
import { unreadableSentence } from "./BlueprintCanvas.jsx";

describe("the unreadable-sheet banner's reason sentence", () => {
  test("a reason carrying its own period gets exactly one", () => {
    expect(unreadableSentence("The sheet is a scanned image with no readable text, so it was not counted."))
      .toBe("The sheet is a scanned image with no readable text, so it was not counted.");
  });

  test("an older stored reason ending in a period reads the same way", () => {
    expect(unreadableSentence("Scanned sheet — vector reading isn't available yet, so it was not counted."))
      .not.toMatch(/\.\./);
  });

  test("a reason with no period gets one", () => {
    expect(unreadableSentence("Nothing on this page could be read")).toBe("Nothing on this page could be read.");
  });

  test("an empty reason renders nothing rather than a bare period", () => {
    expect(unreadableSentence("")).toBe("");
    expect(unreadableSentence(undefined)).toBe("");
  });
});
