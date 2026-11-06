// @vitest-environment jsdom
/**
 * The What gets posted panel (2026-11-06) — the fixture is the Daily Briefing's 09:00 run as the
 * preview endpoint answers for it: the category result, two series, no time column.
 */
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

import type { AutoEffect, PicturePreview } from "@/lib/api";
import { ANALYSIS_KIND } from "@/lib/automationFlow";

const preview: PicturePreview = {
  run_id: "r1", run_at: "2026-11-06T09:00:15Z", said: "", words: "Revenue fell 67.0% on 2026-10-29.",
  results: [{ claim: "Outerwear & Coats was the largest category decline", columns: ["category", "r29", "r28"], rows: 5 },
            { claim: "Daily revenue ramped, then fell", columns: ["d", "rev"], rows: 11 }],
  kinds: { auto: { ok: true, why: "" }, bar: { ok: true, why: "" },
           bar_horizontal: { ok: false, why: "one series only, so Oct 28 would be left out" },
           line: { ok: false, why: "no time column in this result" },
           pie: { ok: false, why: "one series only, so Oct 28 would be left out" },
           counter: { ok: false, why: "needs a single value" } },
  names: { labels: { r29: "Oct 29", r28: "Oct 28" }, y_title: "Revenue" },
  pictures: [{ picture: "chart", kind: "auto", asked: "auto", title: "Outerwear & Coats…", note: "", result: 0,
               image: "data:image/png;base64,AAAA" }],
};

beforeAll(() => {
  vi.stubGlobal("matchMedia", (q: string) => ({ matches: false, media: q, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } }));
});

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  previewStepPicture: vi.fn(async () => preview),
}));

import { readWords, WhatGetsPosted, writeWords } from "./WhatGetsPosted";

const analysis = { kind: ANALYSIS_KIND, config: { question: "What changed in theLook in the last day?" } } as unknown as AutoEffect;
const slack = (config: Record<string, unknown> = {}) => ({ kind: "slack_post",
  config: { bot_id: "b", channel: "#ask_aughor", message: { $from: "step1.summary" }, ...config } }) as unknown as AutoEffect;

describe("the words", () => {
  it("are the bindings the message field holds, both ways", () => {
    expect(readWords({ $from: "step1.summary" })).toEqual({ source: "step1", words: "summary" });
    expect(readWords({ $from: "step1.answer" })).toEqual({ source: "step1", words: "headline" });
    expect(readWords({ $from: "step1.summary" }, { $from: "step1.answer" })).toEqual({ source: "step1", words: "both" });
    expect(readWords("good morning")).toEqual({ source: "", words: "own" });
    expect(writeWords("both", "step1")).toEqual({ message: { $from: "step1.summary" }, headline: { $from: "step1.answer" } });
    expect(writeWords("headline", "step1")).toEqual({ message: { $from: "step1.answer" }, headline: null });
  });
});

describe("WhatGetsPosted", () => {
  it("offers only the kinds this result can take, says why the rest are not, and shows the post", async () => {
    const onChange = vi.fn();
    render(<Theme><WhatGetsPosted automationId="a1" index={1} e={slack()} siblings={[analysis, slack()]}
      onChange={onChange} /></Theme>);
    await waitFor(() => expect(screen.getByTestId("kinds-left-out")).toBeTruthy());
    const left = screen.getByTestId("kinds-left-out").textContent ?? "";
    expect(left).toBe("Not offered for this result — horizontal bars and pie: one series only, so Oct 28 would be "
                      + "left out · line: no time column in this result · number: needs a single value.");
    expect(screen.queryByRole("radio", { name: "Pie" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Bars" })).toBeTruthy();
    expect(screen.getByText("What changed in theLook in the last day?")).toBeTruthy();
    expect(screen.getByTestId("post-preview").textContent).toContain("Revenue fell 67.0% on 2026-10-29.");
    expect((screen.getByLabelText("What r28 is called") as HTMLInputElement).value).toBe("Oct 28");

    fireEvent.click(screen.getByRole("radio", { name: "Headline" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      config: expect.objectContaining({ message: { $from: "step1.answer" }, headline: null }) }));
    fireEvent.click(screen.getByRole("radio", { name: "Table" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      config: expect.objectContaining({ picture: "table" }) }));
  });

  it("keeps a chosen kind on offer even when this result cannot take it", async () => {
    render(<Theme><WhatGetsPosted automationId="a1" index={1} e={slack({ chart_kind: "pie" })}
      siblings={[analysis, slack()]} onChange={vi.fn()} /></Theme>);
    await waitFor(() => expect(screen.getByTestId("kinds-left-out")).toBeTruthy());
    expect(screen.getByRole("radio", { name: "Pie" })).toBeTruthy();
  });
});
