// @vitest-environment jsdom
/**
 * Settings ▸ Appearance, out of `app/page.tsx` and onto the CLARITY kit (2026-10-12). Pinned: the theme in force is
 * the checked one, and choosing the other calls the screen's own setter — the one that writes the stored theme — with
 * exactly that theme, as the inline buttons did. The look card beside it is `LookPanel` (its own test).
 */
import { fireEvent, render, screen } from "@/lib/testing";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ putMyPreference: vi.fn(async () => {}) }));

import { AppearancePanel } from "./AppearancePanel";

describe("Settings ▸ Appearance", () => {
  it("checks the theme in force and hands the other to the screen's setter", () => {
    const setTheme = vi.fn();
    render(<AppearancePanel theme="dark" setTheme={setTheme} />);
    const dark = screen.getByRole("radio", { name: /Dark/ });
    const light = screen.getByRole("radio", { name: /Light/ });
    expect(dark).toHaveAttribute("aria-checked", "true");
    expect(light).toHaveAttribute("aria-checked", "false");
    fireEvent.click(light);
    expect(setTheme).toHaveBeenCalledWith("light");
    expect(setTheme).toHaveBeenCalledTimes(1);
  });

  it("sits beside the look, on one row of cards", () => {
    render(<AppearancePanel theme="light" setTheme={() => {}} />);
    expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    expect(screen.getByTestId("look-panel")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Light/ })).toHaveAttribute("aria-checked", "true");
  });
});
