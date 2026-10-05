// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_LOOK, cleanLook, forgetLook, getLook, setLook } from "./look";

describe("the look", () => {
  afterEach(() => { window.localStorage.clear(); forgetLook(); });

  it("defaults to what the user chose for everyone: indigo, gray, large, 100%", () => {
    expect(getLook()).toEqual({ accent: "indigo", grey: "gray", radius: "large", scaling: "100%" });
  });

  it("never hands the Theme a value that is not one of a knob's own", () => {
    // A person's settings hold other keys too, and an older build may have stored anything.
    const cleaned = cleanLook({ accent: "chartreuse", grey: "slate", radius: 12, scaling: "95%", theme: "light" });
    expect(cleaned).toEqual({ ...DEFAULT_LOOK, grey: "slate", scaling: "95%" });
  });

  it("keeps a knob the incoming settings do not hold", () => {
    expect(cleanLook({ accent: "teal" }, { ...DEFAULT_LOOK, radius: "small" }))
      .toEqual({ ...DEFAULT_LOOK, accent: "teal", radius: "small" });
  });

  it("remembers a change in this browser and tells whoever is listening", async () => {
    const { useLook } = await import("./look");
    const { renderHook, act } = await import("@testing-library/react");
    const seen = renderHook(() => useLook());
    act(() => { setLook({ accent: "jade", radius: "small" }); });
    expect(seen.result.current).toEqual({ ...DEFAULT_LOOK, accent: "jade", radius: "small" });
    forgetLook();   // a new page load reads what the browser kept
    expect(getLook()).toEqual({ ...DEFAULT_LOOK, accent: "jade", radius: "small" });
  });

  it("reads a stored look that is not JSON as the default", () => {
    window.localStorage.setItem("aughor_look", "{not json");
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(getLook()).toEqual(DEFAULT_LOOK);
    quiet.mockRestore();
  });
});
