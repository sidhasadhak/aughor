/**
 * The colour tokens script reads, as hexes at the DEFAULT look — indigo, gray — per skin.
 *
 * Only for where there is no stylesheet to read: the server's render, a headless print, a
 * test. In a browser `lib/tokenColor.ts` reads the live value, so a person's own accent and
 * grey win there. This is a mirror, and mirrors drift; `tokenFallback.test.ts` resolves each
 * name through `aughor-v2/theme/tokens-v2.css` into Radix Themes' own stylesheet and fails
 * on any difference. Change a token's step, or the default look, and that test says what to
 * write here.
 */
export const TOKEN_FALLBACK = {
  dark: {
    "--bg-0": "#111111", "--bg-1": "#191919", "--bg-2": "#191919", "--bg-3": "#111111", "--bg-4": "#313131",
    "--bg-hover": "#2A2A2A", "--bg-sel": "#1D2E62",
    "--b0": "#313131", "--b1": "#3A3A3A", "--b2": "#484848",
    "--t1": "#EEEEEE", "--t2": "#B4B4B4", "--t3": "#B4B4B4", "--t4": "#6E6E6E",
    "--blue3": "#3E63DD", "--blue4": "#9EB1FF",
    "--chart-axis": "#484848", "--chart-grid": "#313131", "--chart-tick": "#6E6E6E",
  },
  light: {
    "--bg-0": "#FFFFFF", "--bg-1": "#F9F9F9", "--bg-2": "#FFFFFF", "--bg-3": "#FFFFFF", "--bg-4": "#E0E0E0",
    "--bg-hover": "#E8E8E8", "--bg-sel": "#E1E9FF",
    "--b0": "#E0E0E0", "--b1": "#D9D9D9", "--b2": "#CECECE",
    "--t1": "#202020", "--t2": "#646464", "--t3": "#646464", "--t4": "#8D8D8D",
    "--blue3": "#3E63DD", "--blue4": "#3A5BC7",
    "--chart-axis": "#CECECE", "--chart-grid": "#E0E0E0", "--chart-tick": "#8D8D8D",
  },
} as const;

export type TokenName = keyof (typeof TOKEN_FALLBACK)["dark"];
