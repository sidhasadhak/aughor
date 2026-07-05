"use client";

import { useState, type ReactNode } from "react";
import { formatCount } from "@/lib/format";

// ── "Show the receipt": click any number to see the exact query + the cell that backs it ──
//
// The backend (`/exploration/{conn}/briefing/ground`) is the source of truth for whether a
// number is grounded — it re-runs the cited finding's query live and matches the numeral
// against the real cells. The client only decides which tokens are worth making clickable
// (magnitude-bearing ones), mirroring the conservative `enforce` rule in grounding.py.

const _NUM_RE = /(?<![\w.])[$€£]?\d[\d,]*(?:\.\d+)?\s?(?:%|mm|bn|[kmbt]|thousand|million|billion|trillion)?(?![\w])/gi;
const _SUFFIX_MULT: Record<string, number> = {
  k: 1e3, thousand: 1e3, m: 1e6, mm: 1e6, million: 1e6,
  b: 1e9, bn: 1e9, billion: 1e9, t: 1e12, trillion: 1e12,
};

/** Mirrors grounding.extract_numerals' `enforce`: a magnitude claim (K/M/B/T suffix or
 *  value ≥ 1000), excluding percentages and calendar years. These are worth proving. */
function isMagnitudeToken(raw: string): boolean {
  const m = raw.trim().match(/^[$€£]?\s?(\d[\d,]*)(\.\d+)?\s?(%|mm|bn|[kmbt]|thousand|million|billion|trillion)?$/i);
  if (!m) return false;
  const suf = (m[3] || "").toLowerCase();
  if (suf === "%") return false;
  const intStr = m[1].replace(/,/g, "");
  const frac = m[2] || "";
  const base = Number(intStr + frac);
  if (Number.isNaN(base)) return false;
  const hasSuffix = suf in _SUFFIX_MULT;
  const value = base * (hasSuffix ? _SUFFIX_MULT[suf] : 1);
  const decimals = frac ? frac.length - 1 : 0;
  const isYear = !suf && decimals === 0 && base >= 1900 && base <= 2100;
  if (isYear) return false;
  return hasSuffix || Math.abs(value) >= 1000;
}

export interface NumberReceipt {
  sql: string;
  /** true = backed by a real cell, false = enforced but not found, null = derived/not enforced. */
  grounded: boolean | null;
  matchedCell: number | null;
  note?: string;
  error?: string;
}

/** Split prose into plain text + clickable magnitude tokens, each rendered via `renderToken`. */
export function withGroundedNumbers(
  text: string,
  renderToken: (token: string, key: string) => ReactNode,
  keyPrefix: string,
): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let mi = 0;
  for (const match of text.matchAll(_NUM_RE)) {
    const tok = match[0];
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    if (isMagnitudeToken(tok)) {
      out.push(renderToken(tok, `${keyPrefix}-n${mi++}`));
    } else {
      out.push(tok);
    }
    last = start + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function fmtCell(v: number | null): string {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return formatCount(v);
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

/**
 * A clickable number that, on click, resolves its receipt (via `resolve`) and shows the
 * exact SQL + the result cell that backs it. Used in the narrative prose and KPI strip.
 */
export function GroundedNumber({
  token,
  resolve,
}: {
  token: string;
  resolve: () => Promise<NumberReceipt>;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [receipt, setReceipt] = useState<NumberReceipt | null>(null);
  const [loading, setLoading] = useState(false);

  async function onClick(e: React.MouseEvent) {
    setPos({ x: e.clientX, y: e.clientY });
    setOpen(true);
    if (!receipt && !loading) {
      setLoading(true);
      try {
        setReceipt(await resolve());
      } catch (err) {
        setReceipt({ sql: "", grounded: null, matchedCell: null, error: err instanceof Error ? err.message : "Failed to load receipt" });
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <>
      <button
        onClick={onClick}
        title="Show the receipt — the query + cell behind this number"
        style={{
          background: "none", border: "none", padding: 0, cursor: "pointer",
          font: "inherit", color: "inherit",
          borderBottom: "1px dashed color-mix(in srgb, var(--blue4) 55%, transparent)",
        }}
      >
        {token}
      </button>
      {open && <ReceiptPopover x={pos.x} y={pos.y} loading={loading} receipt={receipt} onClose={() => setOpen(false)} />}
    </>
  );
}

function ReceiptPopover({
  x, y, loading, receipt, onClose,
}: {
  x: number; y: number; loading: boolean; receipt: NumberReceipt | null; onClose: () => void;
}) {
  const left = Math.max(12, Math.min(x, (typeof window !== "undefined" ? window.innerWidth : 1280) - 392));
  const top = Math.min(y + 12, (typeof window !== "undefined" ? window.innerHeight : 800) - 240);

  const badge = (() => {
    if (!receipt || receipt.error) return null;
    if (receipt.grounded === true) return { label: "✓ Grounded in results", color: "var(--grn3, #4ade80)" };
    if (receipt.grounded === false) return { label: "⚠ Not found in results", color: "var(--amb3, #f5a623)" };
    return { label: "Derived — not enforced against a single cell", color: "var(--t4)" };
  })();

  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 199 }} />
      <div
        onClick={e => e.stopPropagation()}
        style={{
          position: "fixed", left, top, zIndex: 200, width: 380,
          background: "var(--bg-2)", border: "1px solid var(--b2)", borderRadius: "var(--r3)",
          boxShadow: "0 8px 28px rgba(0,0,0,.45)", padding: 13,
          display: "flex", flexDirection: "column", gap: 9,
        }}
      >
        <div className="aug-label" style={{ color: "var(--t3)", letterSpacing: ".05em" }}>Receipt</div>
        {loading && <div style={{ fontSize: 11, color: "var(--t3)" }}>Re-running the query live…</div>}
        {!loading && receipt?.error && (
          <div style={{ fontSize: 11, color: "var(--red4, #ff6b6b)" }}>{receipt.error}</div>
        )}
        {!loading && receipt && !receipt.error && (
          <>
            {badge && (
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 11, fontWeight: 600, color: badge.color }}>{badge.label}</span>
                {receipt.matchedCell != null && (
                  <span style={{ fontSize: 11, color: "var(--t2)" }}>
                    cell = <strong>{fmtCell(receipt.matchedCell)}</strong>
                  </span>
                )}
              </div>
            )}
            {receipt.note && <div style={{ fontSize: 11, color: "var(--t3)" }}>{receipt.note}</div>}
            {receipt.sql && (
              <pre style={{
                margin: 0, fontFamily: "var(--font-code)", fontSize: 10.5, lineHeight: 1.5,
                color: "var(--t2)", background: "var(--bg-1)", border: "1px solid var(--b1)",
                borderRadius: "var(--r2)", padding: "8px 10px", maxHeight: 180, overflow: "auto",
                whiteSpace: "pre-wrap", wordBreak: "break-word",
              }}>{receipt.sql}</pre>
            )}
          </>
        )}
      </div>
    </>
  );
}
