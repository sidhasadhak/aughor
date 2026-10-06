// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { LOOK_KEY } from "@/lib/lookValues";
import { THEME_BOOT } from "@/lib/themeBoot";
import { THEME_KEY } from "@/lib/themeSwitch";

const html = () => document.documentElement;
const boot = () => new Function(THEME_BOOT)();
const attrs = () => ({
  theme: html().getAttribute("data-theme"),
  classes: [...html().classList].filter(c => c === "light" || c === "dark"),
  scheme: html().style.colorScheme,
  accent: html().getAttribute("data-accent-color"),
  grey: html().getAttribute("data-gray-color"),
  radius: html().getAttribute("data-radius"),
  scaling: html().getAttribute("data-scaling"),
});

describe("the theme boot script", () => {
  afterEach(() => {
    localStorage.clear();
    for (const a of ["data-theme", "data-accent-color", "data-gray-color", "data-radius", "data-scaling"]) html().removeAttribute(a);
    html().className = "";
    html().style.colorScheme = "";
  });

  it("paints a person's skin and look before React does", () => {
    localStorage.setItem(THEME_KEY, "light");
    localStorage.setItem(LOOK_KEY, JSON.stringify({ accent: "teal", grey: "slate", radius: "none", scaling: "110%" }));
    html().className = "fonts dark";   // as the server rendered it: the default skin
    boot();
    expect(attrs()).toEqual({ theme: "light", classes: ["light"], scheme: "light", accent: "teal", grey: "slate", radius: "none", scaling: "110%" });
    expect(html().className).toContain("fonts");   // the other classes stand
  });

  it("leaves the default — dark, indigo — when nothing is stored", () => {
    boot();
    expect(attrs()).toEqual({ theme: "dark", classes: ["dark"], scheme: "dark", accent: "indigo", grey: "gray", radius: "large", scaling: "100%" });
  });

  it("puts a knob it cannot read back to the default, and never throws", () => {
    localStorage.setItem(THEME_KEY, "sepia");
    localStorage.setItem(LOOK_KEY, JSON.stringify({ accent: "plaid", radius: "large" }));
    boot();
    expect(attrs()).toMatchObject({ theme: "dark", accent: "indigo", radius: "large" });
    localStorage.setItem(LOOK_KEY, "{not json");
    expect(() => boot()).not.toThrow();
  });
});
