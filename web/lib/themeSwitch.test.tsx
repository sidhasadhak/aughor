// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { applyTheme } from "@/lib/themeSwitch";

const blocker = () =>
  [...document.head.querySelectorAll("style")].find(s => s.textContent?.includes("transition:none"));

describe("applyTheme", () => {
  const realRaf = window.requestAnimationFrame;
  afterEach(() => {
    window.requestAnimationFrame = realRaf;
    document.documentElement.removeAttribute("data-theme");
    document.head.querySelectorAll("style").forEach(s => s.remove());
  });

  it("holds transitions off across the flip and lets them back two frames later", () => {
    const frames: FrameRequestCallback[] = [];
    window.requestAnimationFrame = cb => { frames.push(cb); return frames.length; };
    document.documentElement.setAttribute("data-theme", "dark");

    applyTheme("light");

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(blocker()).toBeTruthy();
    frames.shift()!(0);    // the frame the new theme paints in: transitions still off
    expect(blocker()).toBeTruthy();
    frames.shift()!(16);   // the next frame: transitions are back
    expect(blocker()).toBeUndefined();
  });

  it("leaves the document alone when the theme is already the one asked for", () => {
    document.documentElement.setAttribute("data-theme", "dark");
    applyTheme("dark");
    expect(blocker()).toBeUndefined();
  });
});
