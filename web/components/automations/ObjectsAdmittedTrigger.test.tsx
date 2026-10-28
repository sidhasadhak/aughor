// @vitest-environment jsdom
/**
 * Arc FA, FA-5 — the "Objects admitted" trigger in the kind picker: offered beside every other kind, and its row asks
 * for the entity and the segment whose newly admitted objects fire the chain.
 */
import { render, screen, waitFor, optionsOf } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

import { ConditionRow } from "@/components/automations/AutomationRows";

describe("the Objects admitted row", () => {
  it("lists the kind and asks for the entity and the segment", async () => {
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
