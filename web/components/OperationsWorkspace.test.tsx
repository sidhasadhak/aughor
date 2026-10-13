// @vitest-environment jsdom
/**
 * Operations' five views are each their own rail item, so its switcher row was a second copy of the rail (the user's
 * defect list, 2026-10-13). The rail is the switcher, as on Data.
 */
import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/lib/testing";

vi.mock("next/dynamic", () => ({ default: () => function Panel() { return <div data-testid="ops-panel" />; } }));

const { OperationsWorkspace } = await import("@/components/OperationsWorkspace");

describe("the Operations workspace", () => {
  it("has no switcher row of its own — the rail opens each view", () => {
    render(<OperationsWorkspace layer="monitors" onLayerChange={() => {}} secLens="security" onSecLensChange={() => {}} />);
    expect(screen.getByTestId("ops-panel")).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Operations views" })).toBeNull();
  });
});
