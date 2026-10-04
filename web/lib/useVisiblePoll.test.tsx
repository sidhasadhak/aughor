// @vitest-environment jsdom
/**
 * A hidden layer does not poll. Measured before this (2026-10-04): on the Roster, 33 API calls
 * in 30 s, from the Overview and Attention layers the person had already left.
 */
import { act, render } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LayerVisibleContext, useVisiblePoll } from "@/lib/useVisiblePoll";

function Poller({ fn }: { fn: () => void }) {
  useVisiblePoll(fn, 1000);
  return null;
}

describe("useVisiblePoll", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("polls while its layer shows, stops while hidden, and catches up once on return", () => {
    const fn = vi.fn();
    const at = (show: boolean) => (
      <LayerVisibleContext.Provider value={show}><Poller fn={fn} /></LayerVisibleContext.Provider>);
    const { rerender } = render(at(true));
    act(() => { vi.advanceTimersByTime(3000); });
    expect(fn).toHaveBeenCalledTimes(3);

    rerender(at(false));
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(fn).toHaveBeenCalledTimes(3);              // hidden: not one call

    rerender(at(true));
    expect(fn).toHaveBeenCalledTimes(4);              // shown again: current at once
    act(() => { vi.advanceTimersByTime(1000); });
    expect(fn).toHaveBeenCalledTimes(5);
  });

  it("a background browser tab does not poll either", () => {
    const fn = vi.fn();
    render(<Poller fn={fn} />);                       // outside a Workspace: counts as showing
    const state = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    act(() => { vi.advanceTimersByTime(5000); });
    expect(fn).not.toHaveBeenCalled();
    state.mockReturnValue("visible");
    act(() => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
