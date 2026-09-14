// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useNavCollapsed } from "@/components/shell/useNavCollapsed";
import { NAV_COLLAPSED_KEY, NAV_COLLAPSE_BOOT } from "@/lib/navCollapse";

// The hook follows the attribute through a MutationObserver, whose callbacks run as microtasks.
const settle = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });

describe("the navigation rail's collapsed state", () => {
  afterEach(() => {
    cleanup();
    document.documentElement.removeAttribute("data-nav");
    localStorage.clear();
  });

  it("toggles the attribute on <html>, remembers it, and follows it", async () => {
    const { result } = renderHook(() => useNavCollapsed());
    expect(result.current[0]).toBe(false);

    act(() => result.current[1]());
    await settle();
    expect(document.documentElement.getAttribute("data-nav")).toBe("collapsed");
    expect(localStorage.getItem(NAV_COLLAPSED_KEY)).toBe("1");
    expect(result.current[0]).toBe(true);

    act(() => result.current[1]());
    await settle();
    expect(document.documentElement.hasAttribute("data-nav")).toBe(false);
    expect(localStorage.getItem(NAV_COLLAPSED_KEY)).toBe("0");
    expect(result.current[0]).toBe(false);
  });

  it("is restored before React runs by the boot script", () => {
    localStorage.setItem(NAV_COLLAPSED_KEY, "1");
    new Function(NAV_COLLAPSE_BOOT)();
    expect(document.documentElement.getAttribute("data-nav")).toBe("collapsed");
  });

  it("toggles on ⌘\\, but not while typing in a field", async () => {
    const { result } = renderHook(() => useNavCollapsed());
    act(() => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "\\", metaKey: true })); });
    await settle();
    expect(result.current[0]).toBe(true);

    const field = document.createElement("input");
    document.body.appendChild(field);
    act(() => { field.dispatchEvent(new KeyboardEvent("keydown", { key: "\\", metaKey: true, bubbles: true })); });
    await settle();
    expect(result.current[0]).toBe(true);
    field.remove();
  });
});
