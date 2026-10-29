// @vitest-environment jsdom
/**
 * Arc BG — the Briefing as an edition written for one reader (ROADMAP §3.66, §6 item 58).
 *
 * Opening never spends: the page READS the edition and writes one only on a click. A reader chosen is
 * kept as the person's setting and the edition re-read for them. With no guide the page says so and offers
 * to draft one; a written edition shows its stories, what the gates held back and what was not read.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BriefingEdition as Edition, BriefingGuideResponse, EditionFigure } from "@/lib/api";

const api = vi.hoisted(() => ({
  readBriefingEdition: vi.fn(), writeBriefingEdition: vi.fn(), readBriefingGuide: vi.fn(),
  draftBriefingGuide: vi.fn(), getGroups: vi.fn(), putMyPreference: vi.fn(),
}));
vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), ...api }));
vi.mock("@/components/brief/BriefSchedule", () => ({ BriefSchedule: () => null }));

import { BriefingEdition } from "./BriefingEdition";

const PERIOD = { period: "week", key: "range:last_week:2026-10-19..2026-10-25", preset: "last_week", label: "Weekly",
  start: "2026-10-19", end: "2026-10-26", last_day: "2026-10-25", previous_start: "2026-10-12", previous_end: "2026-10-19",
  last_year_start: null, last_year_end: null, as_of: "2026-10-29", lag_days: 3, lag_source: "learned", still_moving: [],
  covers: "the week 2026-10-19 to 2026-10-25", compared_with: "the week before", last_year_label: null } as unknown as Edition["period"];

const FIG = { id: "aov", label: "Average order", metric: null, unit: "EUR", better: "up", why: "", current: 645, previous: 623,
  last_year: null, rel: 0.035, rel_last_year: null, n: 259, status: "final",
  usual: { mean: 590, low: 566, high: 614, n: 8, mean_text: "€590", low_text: "€566", high_text: "€614" },
  z: 2.3, outside: true, floor: true, streak: 2, extreme: null,
  series: [{ label: "u1", start: "2026-10-05", value: 600 }, { label: "u2", start: "2026-10-12", value: 610 },
           { label: "current", start: "2026-10-19", value: 645 }],
  cells: {}, current_text: "€645", previous_text: "€623", last_year_text: null, like_for_like: "", sql: "SELECT 1" } as EditionFigure;

const GUIDE: BriefingGuideResponse = {
  available: true, published_version: null, editions_read: { version: 1, state: "draft" },
  version: { version: 1, state: "draft", by: "explorer", note: "", created_at: "", published_at: "" },
  versions: [{ version: 1, state: "draft", by: "explorer", note: "", created_at: "", published_at: "" }],
  guide: { business: "A luxury fashion group.", ranges: { week: "steer", month: "", year: "", custom: "", day: "" },
           news: { usual_week: 8, floor_sd: 2 }, comparisons: [], calendar: [], care: [], checks: [], dropped: [],
           readers: [{ group_id: "finance", name: "Finance", watches: "margin", check_ids: [] }], proposed_readers: [] },
};

const WRITTEN: Edition = { built: true, scope_key: "dcc63d83:luxexperience", period: { ...PERIOD, measured: [FIG] },
  reader: { group_id: "finance", name: "Finance" }, headline: "Baskets far above usual", lede: "An ordinary week, made differently.",
  stories: [{ check_ids: ["aov"], reason: "unusual", title: "Top clients carried the basket", body: "The average order was €645.", figures: [FIG] }],
  also_unusual: [], steady: [{ check_id: "sales", line: "Sales held." }], coming_up: [],
  not_read: [{ label: "Prices end on 5 April 2024.", reason: "", tables: [] }],
  withheld: [{ sentence: "Promotions lifted sales.", why: "it claims a cause (“lifted”)" }],
  guide: { version: 1, state: "draft" }, model_calls: 1, generated_at: "2026-10-29T09:00:00Z" };

beforeEach(() => {
  Object.values(api).forEach(f => f.mockReset());
  api.getGroups.mockResolvedValue({ ladder: [], builtin_groups: [], groups: [
    { id: "finance", name: "Finance", kind: "function", description: "", channel_trigger_id: "" }] });
  api.readBriefingGuide.mockResolvedValue(GUIDE);
  api.putMyPreference.mockResolvedValue(undefined);
});

describe("BriefingEdition", () => {
  it("reads on opening and never writes", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "finance" });
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    expect(await screen.findByText(/Not written yet for Finance/)).toBeTruthy();
    expect(api.readBriefingEdition).toHaveBeenCalledWith("dcc63d83", { preset: "last_week" }, undefined, "luxexperience", undefined);
    expect(api.writeBriefingEdition).not.toHaveBeenCalled();
  });

  it("writes only when asked, for the reader on screen", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "finance" });
    api.writeBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    fireEvent.click(await screen.findByRole("button", { name: "Write this week's edition" }));
    await screen.findByTestId("edition-headline");
    expect(api.writeBriefingEdition).toHaveBeenCalledWith("dcc63d83", { preset: "last_week" }, "finance", "luxexperience", undefined);
  });

  it("shows the stories, what the gates held back, and what was not read", async () => {
    api.readBriefingEdition.mockResolvedValue(WRITTEN);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    expect((await screen.findByTestId("edition-headline")).textContent).toBe("Baskets far above usual");
    const story = screen.getByTestId("edition-story");
    expect(within(story).getByText("Far outside its usual range")).toBeTruthy();
    expect(within(story).getByTestId("edition-range-bars")).toBeTruthy();
    expect(within(screen.getByTestId("edition-withheld")).getByText(/Promotions lifted sales/)).toBeTruthy();
    expect(within(screen.getByTestId("edition-not-read")).getByText(/Prices end/)).toBeTruthy();
    expect(screen.getByTestId("edition-dateline").textContent).toMatch(/from a draft guide no person has published/);
    expect(screen.getByTestId("briefing-guide")).toBeTruthy();
  });

  it("keeps a reader chosen as the person's setting and re-reads for them", async () => {
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "finance" });
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    await screen.findByText(/Not written yet for Finance/);
    fireEvent.click(screen.getByRole("radio", { name: "The organisation" }));
    await waitFor(() => expect(api.putMyPreference).toHaveBeenCalledWith("briefing_reader", ""));
    await waitFor(() => expect(api.readBriefingEdition).toHaveBeenLastCalledWith(
      "dcc63d83", { preset: "last_week" }, "", "luxexperience", undefined));
    expect(api.writeBriefingEdition).not.toHaveBeenCalled();
  });

  it("with no guide, says so and drafts one only on a click", async () => {
    api.readBriefingGuide.mockResolvedValue({ ...GUIDE, available: false, guide: null, version: null, editions_read: null, versions: [] });
    api.readBriefingEdition.mockResolvedValue({ built: false, scope_key: "c", period: PERIOD, reader: "" });
    api.draftBriefingGuide.mockResolvedValue(GUIDE);
    render(<BriefingEdition connectionId="dcc63d83" schema="luxexperience" />);
    const empty = await screen.findByTestId("edition-no-guide");
    expect(api.draftBriefingGuide).not.toHaveBeenCalled();
    fireEvent.click(within(empty).getByRole("button", { name: "Draft the guide" }));
    await waitFor(() => expect(api.draftBriefingGuide).toHaveBeenCalledWith("dcc63d83", "luxexperience"));
  });
});
