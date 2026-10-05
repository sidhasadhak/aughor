// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BriefingDelivery, BriefingRangeBlock } from "@/lib/api";

import { BriefDeliveries, versionWords } from "./BriefDeliveries";

const api = vi.hoisted(() => ({ listBriefingDeliveries: vi.fn(), getBriefingDelivery: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({ ...(await original<typeof import("@/lib/api")>()), ...api }));

const BLOCK = {
  period: "week", key: "range:last_week:2026-09-21..2026-09-27", preset: "last_week", label: "Weekly", start: "2026-09-21",
  end: "2026-09-28", last_day: "2026-09-27", covers: "2026-09-21 to 2026-09-27", compared_with: "the week before",
  lag_days: 1, lag_source: "default", still_moving: [], last_year_label: null, unmeasured: [],
  measured: [{ name: "Revenue", metric: "revenue", unit: "USD", time_kind: "flow", confirmed: true, current: 100, previous: 90,
    last_year: null, rel: 0.11, rel_last_year: null, status: "final", current_text: "$100", previous_text: "$90" }],
} as unknown as BriefingRangeBlock;

const sent = (id: string, extra: Partial<BriefingDelivery> = {}): BriefingDelivery => ({
  id, version: 1, covers: BLOCK.covers, label: "Weekly", scope_key: "thelook", sent_at: "2026-09-28T09:00:00+00:00",
  to: "#ask_aughor as Aughor", to_kind: "slack", subscription_id: "s1", subscription_name: "Weekly to leadership",
  departure_id: "dep-1", receipt_line: "Receipt dep-1", held_lines: 0, restated_since: false, ...extra,
});

beforeEach(() => { for (const f of Object.values(api)) f.mockReset(); });

describe("a Briefing's deliveries", () => {
  it("lists each send with the version that left, and says when it has been restated since", async () => {
    api.listBriefingDeliveries.mockResolvedValue({ current_version: 2,
      deliveries: [sent("d2", { version: 2, to: "Leadership webhook", to_kind: "trigger" }), sent("d1", { restated_since: true })] });
    render(<BriefDeliveries connectionId="thelook" scopeKey="thelook" block={BLOCK} />);
    expect(await screen.findByText("version 1 — restated since, version 2 now")).toBeInTheDocument();
    expect(screen.getByText("version 2, the one on this page")).toBeInTheDocument();
    expect(api.listBriefingDeliveries).toHaveBeenCalledWith("thelook", "2026-09-21 to 2026-09-27", "thelook", "week");
    expect(screen.getByText("Delivered · 2 sends")).toBeInTheDocument();
  });

  it("opens the Briefing as it was sent, not as it stands", async () => {
    api.listBriefingDeliveries.mockResolvedValue({ current_version: 2, deliveries: [sent("d1", { restated_since: true })] });
    api.getBriefingDelivery.mockResolvedValue({ ...sent("d1", { restated_since: true, held_lines: 1 }), connection_id: "thelook",
      as_of: "2026-09-28", current_version: 2, briefing: { narrative: "Revenue rose to 100.\n\nReturns were flat.", period: BLOCK } });
    render(<BriefDeliveries connectionId="thelook" scopeKey="thelook" block={BLOCK} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open what was sent" }));
    expect(api.getBriefingDelivery).toHaveBeenCalledWith("d1");
    const box = await screen.findByTestId("brief-sent-version");
    expect(await screen.findByText("Revenue rose to 100.")).toBeInTheDocument();
    expect(box.textContent).toContain("restated since: version 2 is on the page");
    expect(box.textContent).toContain("1 line of it was held at the gate");
    expect(box.textContent).toContain("$100");                          // its own measured table, as sent
    fireEvent.click(screen.getByRole("button", { name: "Close it" }));
    expect(screen.queryByTestId("brief-sent-version")).toBeNull();
  });

  it("says so when nothing has been sent, and words a version with no number", async () => {
    api.listBriefingDeliveries.mockResolvedValue({ current_version: null, deliveries: [] });
    render(<BriefDeliveries connectionId="thelook" scopeKey="thelook" block={BLOCK} />);
    expect(await screen.findByText(/has not been sent to anyone/)).toBeInTheDocument();
    expect(versionWords(sent("x", { version: null }), 3)).toBe("version not recorded");
  });
});
