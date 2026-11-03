"use client";

/**
 * BrandLogos: each connector's and integration's mark, drawn inline with no network request. The marks are data in
 * `brandMarks.ts`; the few here with no published mark are drawn by hand. `BrandTile` is how a mark sits on a page: a
 * white tile, so a brand's own colour reads true on either skin, Slack's aubergine and Notion's black included.
 */

import React from "react";
import { brandMark } from "@/components/brandMarks";
import { CONNECTORS } from "@/lib/connectors.gen";

// DE-3b: the colour is one fact on each engine's declaration (`aughor/connectors/declarations.py`,
// via `lib/connectors.gen.ts`); the drawings below are hand-made and stay here.
export const BRAND_COLORS: Record<string, string> = Object.fromEntries(
  Object.values(CONNECTORS).map(c => [c.type, c.brandColor]),
);

export function brandColor(type: string): string {
  return BRAND_COLORS[type] ?? "#8a8a93";
}

export function BrandLogo({ type, size = 20 }: { type: string; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 24 24" } as const;
  const mark = brandMark(type);
  if (mark) {
    return (
      <svg {...p} aria-hidden="true" style={{ display: "block" }}>
        {"parts" in mark ? mark.parts.map(x => <path key={x.d} fill={x.fill} d={x.d} />) : <path fill={mark.color} d={mark.d} />}
      </svg>
    );
  }
  switch (type) {
    case "duckdb":
      return (
        <svg {...p}>
          <circle cx="11" cy="11.5" r="7" fill="#FBBF24" />
          <circle cx="9" cy="9.8" r="1.1" fill="#1a1a1a" />
          <path d="M16 11l4.2 1.1-4.2 1.1z" fill="#F59E0B" />
        </svg>
      );
    case "motherduck":
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="9.5" fill="#FFD000" />
          <circle cx="9.4" cy="9.6" r="1.2" fill="#1a1a1a" />
          <circle cx="14" cy="9.6" r="1.2" fill="#1a1a1a" />
          <path d="M16.5 12l3.5 1-3.5 1z" fill="#E8A200" />
          <path d="M8 15c1.2 1.4 6.8 1.4 8 0" stroke="#1a1a1a" strokeWidth={1.2} fill="none" strokeLinecap="round" />
        </svg>
      );
    case "exasol":
      return (
        <svg {...p}>
          <rect x="2" y="2" width="20" height="20" rx="5" fill="#1B68DF" />
          <path d="M7.5 8.5l9 7M16.5 8.5l-9 7" stroke="#fff" strokeWidth={1.8} strokeLinecap="round" />
        </svg>
      );
    case "local_upload":
      return (
        <svg {...p} fill="none" stroke="#3B82F6" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 15V4" /><path d="m7.5 8.5 4.5-4.5 4.5 4.5" />
          <path d="M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16" />
        </svg>
      );
    case "federated":
      return (
        <svg {...p} fill="none" stroke="#34d399" strokeWidth={1.7}>
          <circle cx="7" cy="7" r="3" /><circle cx="17" cy="7" r="3" /><circle cx="12" cy="17" r="3" />
          <path d="M9 9l2 5M15 9l-2 5" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg {...p} fill="none" stroke="#9a9aa3" strokeWidth={1.6} strokeLinecap="round">
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
        </svg>
      );
  }
}

/** The engines drawn by hand above, which have no published mark to look up. */
const DRAWN = new Set(["duckdb", "motherduck", "exasol", "local_upload", "federated"]);

/** A mark on its tile. A name with no mark (a custom server's) shows its first letter rather than someone else's logo. */
export function BrandTile({ type, size = 28 }: { type: string; size?: number }) {
  const known = !!brandMark(type) || DRAWN.has(type);
  return (
    <span aria-hidden="true" style={{ width: size, height: size, flexShrink: 0, display: "inline-flex", alignItems: "center",
      justifyContent: "center", background: "#fff", border: "1px solid var(--card-edge)", borderRadius: "var(--r2)",
      color: "#444", fontWeight: 600, fontSize: Math.round(size * 0.46) }}>
      {known ? <BrandLogo type={type} size={Math.round(size * 0.62)} /> : type.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
