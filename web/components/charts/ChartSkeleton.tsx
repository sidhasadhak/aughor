"use client";

/**
 * Chart placeholders on the design system's shimmer (.aug-skeleton), shaped like what they
 * replace — a number, a line or bars — so the frame does not jump when the chart arrives. The
 * shimmer's reduced-motion frame is a flat fill; there is no pulse and no spinner.
 */
interface Props {
  variant?: "bar" | "line" | "number";
  height?: number;
}

const R = "var(--r1)";

export function ChartSkeleton({ variant = "bar", height = 200 }: Props) {
  if (variant === "number") {
    return (
      <div aria-hidden className="flex flex-col gap-2">
        <div className="aug-skeleton" style={{ height: 22, width: 128, borderRadius: R }} />
        <div className="aug-skeleton" style={{ height: 11, width: 80, borderRadius: R }} />
      </div>
    );
  }

  if (variant === "line") {
    return (
      <div aria-hidden style={{ height }}>
        <div className="flex items-end gap-1 h-full px-2 pb-6 pt-4">
          {Array.from({ length: 12 }).map((_, i) => {
            const pct = 30 + Math.sin(i * 0.6) * 25 + (i % 3) * 8;
            return (
              <div key={i} className="aug-skeleton flex-1" style={{ height: `${Math.max(10, pct)}%`, borderRadius: R }} />
            );
          })}
        </div>
      </div>
    );
  }

  // bar skeleton — horizontal bars of varying widths
  return (
    <div aria-hidden className="flex flex-col gap-2 py-2" style={{ height }}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="aug-skeleton flex-shrink-0" style={{ width: 80, height: 11, borderRadius: R }} />
          <div className="aug-skeleton" style={{ width: `${30 + (i % 4) * 15}%`, height: 16, borderRadius: R }} />
        </div>
      ))}
    </div>
  );
}
