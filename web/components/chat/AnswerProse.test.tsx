// @vitest-environment jsdom
/**
 * SP-10 — the answer reads as designed prose (decision 22(b): a maintained
 * markdown renderer plus the cards). The receipt's own lines, held here:
 * no literal backticks, no red hyphens in ids or dates, lists render, ids are
 * copyable mono chips, and paragraph-length answers never wear display type.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AnswerProse, readsAsProse } from "@/components/chat/AnswerProse";

describe("AnswerProse", () => {
  it("reads a column of months' first days as months, and leaves a column of days alone", () => {
    // Q3 (2026-10-03): the answer's table wrote "2025-09-01" under an axis reading "Sep 2025".
    const { container } = render(<AnswerProse text={"| Month | Revenue |\n| :--- | :--- |\n| 2025-09-01 | $54,076 |\n"
      + "| 2025-10-01 | $60,410 |\n\n| Day | Orders |\n| --- | --- |\n| 2026-03-01 | 12 |\n| 2026-03-02 | 14 |"} />);
    const cells = [...container.querySelectorAll("td")].map((td) => td.textContent);
    expect(cells).toEqual(["Sep 2025", "$54,076", "Oct 2025", "$60,410", "2026-03-01", "12", "2026-03-02", "14"]);
    // one row: its first-of-month date may be the day itself
    const one = render(<AnswerProse text={"| Day | Orders |\n| --- | --- |\n| 2026-03-01 | 12 |"} />);
    expect(one.container.querySelector("td")?.textContent).toBe("2026-03-01");
  });

  it("renders inline code as a copyable chip — never a literal backtick", async () => {
    const writeText = vi.fn();
    Object.assign(navigator, { clipboard: { writeText } });
    const { container } = render(
      <AnswerProse text={"The draft is staged as `automation_draft` in the inbox."} />);
    expect(container.textContent).not.toContain("`");
    await userEvent.click(screen.getByRole("button", { name: "automation_draft" }));
    expect(writeText).toHaveBeenCalledWith("automation_draft");
  });

  it("never tints an id's hyphen runs as losses, and lifts the id out as a chip", () => {
    const { container } = render(
      <AnswerProse text={"ONE proposal staged (proposal c0e1c05a-3f4d-4d07-821f-fcc1e4c52ac7): accepted or refused together."} />);
    expect(container.querySelector(".text-red-400")).toBeNull();
    expect(screen.getByRole("button", { name: "c0e1c05a-3f4d-4d07-821f-fcc1e4c52ac7" })).toBeInTheDocument();
  });

  it("colours nothing: bold or normal text only", () => {
    // The user, 2026-09-30, over an Agent answer whose text turned red from "-03-02" to the
    // end of its paragraph: "no colouring of the output text at all — only bold or normal".
    const { container } = render(
      <AnswerProse text={"Refunds moved -$2.1M while signups rose +12% *quietly* between "
        + "2026-03-02 and 2026-09-01. **Outerwear & Coats** led."} />);
    expect(container.querySelector("[class*='text-red'], [class*='text-emerald'], [class*='text-green']"))
      .toBeNull();
    expect(container.querySelector("em")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("Outerwear & Coats");
    expect(container.textContent).toContain("rose +12% quietly between 2026-03-02 and 2026-09-01.");
  });

  it("renders markdown lists as lists, not run-on prose", () => {
    const { container } = render(
      <AnswerProse text={"Two things:\n\n- which channel\n- which sender\n\nGive me those."} />);
    expect(container.querySelectorAll("li")).toHaveLength(2);
  });

  it("renders a markdown table as a table", () => {
    const { container } = render(
      <AnswerProse text={"| Route | Flights |\n| :--- | :--- |\n| ZRH-LHR | 108 |"} />);
    expect(container.querySelector("table")).not.toBeNull();
    expect(container.textContent).toContain("ZRH-LHR");
  });

  it("renders headings as bold paragraphs — one type scale in an answer", () => {
    const { container } = render(<AnswerProse text={"## What happened\n\nIt staged."} />);
    expect(container.querySelector("h2")).toBeNull();
    expect(container.textContent).toContain("What happened");
  });

  it("never renders raw HTML or images", () => {
    const { container } = render(
      <AnswerProse text={'Before <img src="x" onerror="alert(1)"> after ![alt](http://x/y.png)'} />);
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("readsAsProse", () => {
  it("keeps a one-line conclusion on the headline treatment", () => {
    expect(readsAsProse("Revenue held at $1.2M this week.")).toBe(false);
  });
  it("sends structure and length to the prose renderer", () => {
    expect(readsAsProse("Staged.\n\n- a\n- b")).toBe(true);
    expect(readsAsProse("has `code` in it")).toBe(true);
    expect(readsAsProse("x".repeat(230))).toBe(true);
  });
});
