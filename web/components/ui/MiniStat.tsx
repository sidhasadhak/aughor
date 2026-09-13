import type { ReactNode } from "react";

/** Compact summary stat — a figure and its label, in the summary rows above list screens
 *  (Inbox, Monitors, Investigations). The figure is 22px mono and tabular: the display step
 *  is only ever a number. A hairline frame on the page's plane — never a shadow. Keep the
 *  `value` a real, computed figure — never a placeholder. */
export function MiniStat({ value, label, tone = "var(--t1)" }: {
  value: ReactNode;
  label: string;
  tone?: string;
}) {
  return (
    <div style={{
      flex: 1, minWidth: 0,
      background: "var(--bg-2)", border: "1px solid var(--b1)",
      borderRadius: "var(--r3)", padding: "10px 12px",
    }}>
      <div className="aug-fs-display aug-num" style={{
        fontWeight: 600, color: tone, lineHeight: 1,
      }}>{value}</div>
      <div className="aug-fs-xs" style={{ color: "var(--t3)", marginTop: 6 }}>{label}</div>
    </div>
  );
}

/** Horizontal row wrapper for a set of MiniStats. */
export function MiniStatRow({ children, style }: { children: ReactNode; style?: React.CSSProperties }) {
  return <div style={{ display: "flex", gap: 12, marginBottom: 16, ...style }}>{children}</div>;
}
