// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Theme } from "@radix-ui/themes";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const putMyPreference = vi.fn(async (_key: string, _value: unknown) => {});
vi.mock("@/lib/api", () => ({ putMyPreference: (key: string, value: unknown) => putMyPreference(key, value) }));

import { LookPanel } from "@/components/LookPanel";
import { DEFAULT_LOOK, forgetLook, getLook } from "@/lib/look";

const panel = () => render(<Theme><LookPanel /></Theme>);

describe("the look panel", () => {
  beforeEach(() => { putMyPreference.mockClear(); });
  afterEach(() => { cleanup(); window.localStorage.clear(); forgetLook(); });

  it("marks the look in force", () => {
    panel();
    expect(screen.getByRole("radio", { name: "Indigo" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Teal" })).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("button", { name: "Back to the default" })).toBeNull();
  });

  it("moves the page and writes the person's own setting, one key per knob", () => {
    panel();
    fireEvent.click(screen.getByRole("radio", { name: "Teal" }));
    expect(getLook().accent).toBe("teal");
    expect(putMyPreference.mock.calls).toEqual([["accent", "teal"]]);
    expect(screen.getByRole("radio", { name: "Teal" })).toHaveAttribute("aria-checked", "true");
  });

  it("offers the way back once the look is not the default, and it stores all four", () => {
    panel();
    fireEvent.click(screen.getByRole("radio", { name: "Sage" }));
    putMyPreference.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Back to the default" }));
    expect(getLook()).toEqual(DEFAULT_LOOK);
    expect(Object.fromEntries(putMyPreference.mock.calls)).toEqual(DEFAULT_LOOK);
  });
});
