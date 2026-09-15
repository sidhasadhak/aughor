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

  it("keeps the one real semantic color: a signed delta", () => {
    const { container } = render(
      <AnswerProse text={"Refunds moved -$2.1M while signups rose +12%."} />);
    expect(container.querySelector(".text-red-400")?.textContent).toBe("-$2.1M");
    expect(container.querySelector(".text-emerald-400")?.textContent).toBe("+12%");
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
