// @vitest-environment jsdom
/**
 * Arc FA, FA-5 — the "Objects admitted" trigger in the kind picker.
 *
 * The picker is a synchronous `<select>` over the client's own kind list, while whether the
 * trigger may be offered is the server's (`automations.objects_admitted`, read through the
 * served palette). So: hidden while the palette does not list it, offered once it does, and a
 * row that already IS one keeps its kind — a stored trigger must stay readable after its flag
 * went off, never silently relabelled as whatever the first option is.
 */
import { render, screen, waitFor, optionsOf } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import { ConditionRow, offeredConditionKinds } from "@/components/automations/AutomationRows";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  getAutomationPalette: vi.fn(async () => [
    { kind: "schedule", group: "trigger", label: "Schedule", description: "", icon: "clock",
      priority: 10, publishes: [], bindable: [], availability: "ready", reason: "" },
    { kind: "objects_admitted", group: "trigger", label: "Objects admitted", description: "",
      icon: "filter", priority: 55, publishes: [], bindable: [], availability: "ready", reason: "" },
  ]),
}));

const kinds = (served: Set<string> | null, current = "schedule") =>
  offeredConditionKinds(served, current).map(k => k.value);

describe("which trigger kinds the picker offers", () => {
  it("hides the flagged kind until the deployment's palette lists it", () => {
    expect(kinds(null)).not.toContain("objects_admitted");
    expect(kinds(new Set(["schedule"]))).not.toContain("objects_admitted");
    expect(kinds(new Set(["schedule"]))).toContain("promise_breached");      // every other kind, as before
  });

  it("offers it once the palette lists it", () => {
    expect(kinds(new Set(["schedule", "objects_admitted"]))).toContain("objects_admitted");
  });

  it("keeps a stored trigger of that kind readable after its flag went off", () => {
    expect(kinds(new Set(["schedule"]), "objects_admitted")).toContain("objects_admitted");
  });
});

describe("the Objects admitted row", () => {
  it("lists the kind from the served palette and asks for the entity and the segment", async () => {
    const onChange = vi.fn();
    render(<ConditionRow c={{ kind: "objects_admitted", config: { entity: "order", segment: "overdue_dispatch" } }}
      onChange={onChange} />);
    const picker = screen.getByLabelText("Trigger kind");
    await waitFor(() => expect(optionsOf(picker).map(o => o.text)).toContain("Objects admitted"));
    expect((screen.getByLabelText("Entity") as HTMLInputElement).value).toBe("order");
    expect((screen.getByLabelText("Segment") as HTMLInputElement).value).toBe("overdue_dispatch");
    expect(screen.getByText(/The first check records the objects already in/)).toBeTruthy();
  });
});
