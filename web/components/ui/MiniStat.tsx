import type { ReactNode } from "react";

/** Compact summary stat tile — a single big number + label. Used in the summary
 *  rows above list screens (Inbox, Monitors, Investigations). Token-driven so it
 *  follows dark/light. Keep the `value` a real, computed figure — never a placeholder. */
export function MiniStat({ value, label, tone = "var(--t1)" }: {
  value: ReactNode;
  label: string;
  tone?: string;
}) {
  return (
    <div style={{
      flex: 1, minWidth: 0,
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderRadius: "var(--r3)", padding: "12px 16px",
    }}>
      <div style={{
        fontSize: 22, fontWeight: 700, color: tone,
        letterSpacing: "-.02em", lineHeight: 1.1, fontVariantNumeric: "tabular-nums",
      }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--t3)", marginTop: 5 }}>{label}</div>
    </div>
  );
}

/** Horizontal row wrapper for a set of MiniStats. */
export function MiniStatRow({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return <div style={{ display: "flex", gap: 12, marginBottom: 16, ...style }}>{children}</div>;
}
