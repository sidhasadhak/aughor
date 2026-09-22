// CB-5 — the visibility line renders the sentence the door wrote, and nothing when it cannot.
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { VisibilityLine } from "./VisibilityLine";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, getVisibility: vi.fn() };
});

const seen = {
  tables: { total: 5, mapped: 3, excluded: 1, in_scope: 4, share: 0.75, band: "orange" as const, basis: "profiler" as const,
            unmapped: ["events_raw"], exclusions: [], note: "" },
  joins: { total: 8, measured: 5, share: 0.625 },
  definitions: [{ definition: "revenue", holds: 3, automations: ["a1"], latest: "" }],
  top_blocker: { definition: "revenue", holds: 3, automations: ["a1"], latest: "" },
  line: "sees 3 of 4 tables (75%), 1 excluded · joins measured 5 of 8 · approve `revenue` and 3 held sends unblock",
  exclusion_reasons: ["system_table"],
};

describe("VisibilityLine", () => {
  it("renders the door's sentence with the detail on hover", async () => {
    vi.mocked(api.getVisibility).mockResolvedValue(seen);
    render(<VisibilityLine connectionId="c1" schema="main" />);
    const el = await screen.findByTestId("visibility-line");
    expect(el.textContent).toBe(seen.line);
    expect(el.getAttribute("title")).toContain("not yet: events_raw");
    expect(el.getAttribute("title")).toContain("revenue (3)");
    expect(api.getVisibility).toHaveBeenCalledWith("c1", "main");
  });

  it("renders nothing rather than a guess when the door fails", async () => {
    vi.mocked(api.getVisibility).mockRejectedValue(new Error("down"));
    const { container } = render(<VisibilityLine connectionId="c1" />);
    await waitFor(() => expect(api.getVisibility).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
