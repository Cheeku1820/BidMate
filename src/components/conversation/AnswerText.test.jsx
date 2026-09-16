import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import AnswerText from "./AnswerText.jsx";

describe("AnswerText", () => {
  it("renders paragraphs, lists, bold and italic, and nothing else", () => {
    const { container } = render(<AnswerText text={"Two items block export.\n\n- **E2.1** duplex, *Missing information*\n- E3.1 fixture\n\nSet the scale from the blueprint."} />);
    expect(container.querySelectorAll("p")).toHaveLength(2);
    const items = container.querySelectorAll("ul > li");
    expect(items).toHaveLength(2);
    expect(items[0].querySelector("strong").textContent).toBe("E2.1");
    expect(items[0].querySelector("em").textContent).toBe("Missing information");
  });

  it("never interprets markup in the text", () => {
    const { container } = render(<AnswerText text={"<img src=x onerror=alert(1)> and # not a heading"} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)> and # not a heading");
  });

  it("renders a still-streaming fragment without a trailing list break", () => {
    const { container } = render(<AnswerText text={"- first\n- sec"} />);
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });
});
