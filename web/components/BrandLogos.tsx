"use client";

/**
 * BrandLogos — compact, brand-coloured SVG marks for each connector type.
 *
 * These are recognisable, lightweight reproductions (not pixel-perfect brand
 * assets) drawn inline so they render crisply on the dark theme without any
 * network requests. `brandColor` exposes the accent for tinting tiles/borders.
 */

import React from "react";

export const BRAND_COLORS: Record<string, string> = {
  duckdb:       "#FBBF24",
  postgres:     "#6f9bcc",
  bigquery:     "#4285F4",
  snowflake:    "#29B5E8",
  mysql:        "#00A3C7",
  motherduck:   "#FFD000",
  exasol:       "#1B68DF",
  gsheets:      "#0F9D58",
  local_upload: "#3B82F6",
  s3:           "#569A31",
  stripe:       "#7a73ff",
  hubspot:      "#FF7A59",
  salesforce:   "#00A1E0",
  confluence:   "#2684FF",
  notion:       "#c4c4cc",
  federated:    "#34d399",
};

export function brandColor(type: string): string {
  return BRAND_COLORS[type] ?? "#8a8a93";
}

export function BrandLogo({ type, size = 20 }: { type: string; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 24 24" } as const;
  switch (type) {
    case "snowflake":
      return (
        <svg {...p} fill="none" stroke="#29B5E8" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2v20" /><path d="M2 12h20" /><path d="M4.5 4.5l15 15" /><path d="M19.5 4.5l-15 15" />
          <path d="M12 5l-2 2M12 5l2 2" /><path d="M12 19l-2-2M12 19l2-2" />
          <path d="M5 12l2-2M5 12l2 2" /><path d="M19 12l-2-2M19 12l-2 2" />
        </svg>
      );
    case "stripe":
      return (
        <svg {...p}>
          <rect x="2" y="2" width="20" height="20" rx="5" fill="#635BFF" />
          <path d="M11.6 9.4c0-.6.5-.8 1.2-.8 1 0 2.4.3 3.5.9V6.3a8 8 0 0 0-3.5-.7c-2.8 0-4.7 1.5-4.7 4 0 3.9 5.3 3.2 5.3 4.9 0 .6-.5.9-1.4.9-1.1 0-2.6-.5-3.7-1.1v3.2c1.2.5 2.5.8 3.7.8 2.9 0 4.9-1.4 4.9-4 0-4.2-5.3-3.4-5.3-4.9z" fill="#fff" />
        </svg>
      );
    case "s3":
      return (
        <svg {...p} fill="#569A31">
          <path d="M5 4h14l-1.4 15.1a1.5 1.5 0 0 1-1.5 1.4H7.9a1.5 1.5 0 0 1-1.5-1.4L5 4z" />
          <rect x="4" y="3.2" width="16" height="2.2" rx="1" fill="#6fb83f" />
        </svg>
      );
    case "salesforce":
      return (
        <svg {...p} fill="#00A1E0">
          <path d="M10 18a4.2 4.2 0 0 1-.8-8.3 5 5 0 0 1 9.2-1.1A3.6 3.6 0 0 1 18 18H10z" />
        </svg>
      );
    case "postgres":
      return (
        <svg {...p} fill="none" stroke="#7ba8e0" strokeWidth={1.6} strokeLinecap="round">
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
        </svg>
      );
    case "mysql":
      return (
        <svg {...p} fill="none" stroke="#00A3C7" strokeWidth={1.6} strokeLinecap="round">
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
          <path d="M16 19c1.5 0 2.5 1 3 2" stroke="#F29111" />
        </svg>
      );
    case "bigquery":
      return (
        <svg {...p} fill="none" stroke="#4285F4" strokeWidth={1.8} strokeLinecap="round">
          <circle cx="10.5" cy="10.5" r="6" />
          <path d="m15 15 4.5 4.5" />
          <path d="M10.5 8v5M8 10.5h5" stroke="#4285F4" strokeWidth={1.4} />
        </svg>
      );
    case "hubspot":
      return (
        <svg {...p} fill="none" stroke="#FF7A59" strokeWidth={1.7} strokeLinecap="round">
          <circle cx="10" cy="15" r="4.2" />
          <circle cx="18" cy="6.5" r="2.4" fill="#FF7A59" stroke="none" />
          <path d="M16.4 8 12 11.5" /><path d="M10 10.8V8" />
        </svg>
      );
    case "confluence":
      return (
        <svg {...p} fill="#2684FF">
          <path d="M3 17.2c3.4-4.4 7-1.6 10.4-3.5l2.8 4.4c-3.9 2.4-7.8-1-10.7 1.4L3 17.2z" opacity={0.85} />
          <path d="M21 6.8c-3.4 4.4-7 1.6-10.4 3.5L7.8 5.9c3.9-2.4 7.8 1 10.7-1.4L21 6.8z" />
        </svg>
      );
    case "notion":
      return (
        <svg {...p} fill="none" stroke="#d4d4d8" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
          <rect x="4" y="3" width="16" height="18" rx="2" />
          <path d="M8.5 16.5V8l7 8.5V8" />
        </svg>
      );
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
    case "gsheets":
      return (
        <svg {...p}>
          <path d="M13 2H6.5A1.5 1.5 0 0 0 5 3.5v17A1.5 1.5 0 0 0 6.5 22h11a1.5 1.5 0 0 0 1.5-1.5V8l-6-6z" fill="#0F9D58" />
          <path d="M13 2l6 6h-6z" fill="#0a7a44" />
          <path d="M8.5 12h7M8.5 15h7M8.5 18h7M11 11v8M14.5 11v8" stroke="#fff" strokeWidth={1} />
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
