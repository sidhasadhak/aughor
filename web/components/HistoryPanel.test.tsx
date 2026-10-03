// @vitest-environment jsdom
/**
 * React's "a button cannot be a descendant of a button" on every History load with a failed run
 * (2026-10-02): its "ask why" sat inside the row's button. It sits beside the row now, and still asks.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/commandRegistry", () => ({ askSpotlight: vi.fn() }));
vi.mock("@/lib/events", () => ({ subscribeKernelEvents: () => () => {} }));

import { askSpotlight } from "@/lib/commandRegistry";
import { HistoryPanel } from "@/components/HistoryPanel";

const FAILED = { id: "inv1", question: "What was revenue?", status: "failed", kind: "investigation", started_at: "2026-10-02T12:00:00Z",
                 headline: "", hypothesis_count: 0, query_count: 1, connection_id: "8233e4fd" };

afterEach(() => vi.unstubAllGlobals());

describe("a failed run in the History list", () => {
  it("keeps 'ask why' out of the row's button, and it still asks", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      json: async () => (String(url).endsWith("/indexed-ids") ? { ids: [] } : [FAILED]),
    })));
    const onSelect = vi.fn();
    const { container } = render(<HistoryPanel selectedId={null} onSelect={onSelect} />);
    const ask = await waitFor(() => screen.getByRole("button", { name: "ask why" }));
    expect(container.querySelector("button button")).toBeNull();
    ask.click();
    expect(askSpotlight).toHaveBeenCalledWith(expect.stringContaining("(id inv1) fail?"));
    expect(onSelect).not.toHaveBeenCalled();
  });
});
