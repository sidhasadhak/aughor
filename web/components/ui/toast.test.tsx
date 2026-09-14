// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toaster, dismissToast, toast } from "@/components/ui/toast";

function setTabHidden(hidden: boolean) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => (hidden ? "hidden" : "visible"),
  });
  act(() => { document.dispatchEvent(new Event("visibilitychange")); });
}

describe("a toast's dismiss timer", () => {
  const raised: string[] = [];
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => {
    act(() => { raised.splice(0).forEach(id => dismissToast(id)); });
    setTabHidden(false);
    cleanup();
    vi.useRealTimers();
  });

  it("runs out on its own while the tab is visible", () => {
    render(<Toaster />);
    act(() => { raised.push(toast.info("Saved", { duration: 1000 })); });
    expect(screen.getByText("Saved")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.queryByText("Saved")).toBeNull();
  });

  it("holds while the tab is hidden, then runs its full time once the reader is back", () => {
    render(<Toaster />);
    act(() => { raised.push(toast.info("Exported", { duration: 1000 })); });
    setTabHidden(true);
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByText("Exported")).toBeTruthy();
    setTabHidden(false);
    act(() => { vi.advanceTimersByTime(999); });
    expect(screen.getByText("Exported")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(1); });
    expect(screen.queryByText("Exported")).toBeNull();
  });
});
