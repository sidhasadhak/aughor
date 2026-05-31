"use client";

interface Props {
  variant?: "bar" | "line" | "number";
  height?: number;
}

export function ChartSkeleton({ variant = "bar", height = 200 }: Props) {
  if (variant === "number") {
    return (
      <div className="flex flex-col gap-2 animate-pulse">
        <div className="h-8 w-32 rounded bg-zinc-700/50" />
        <div className="h-3 w-20 rounded bg-zinc-700/30" />
      </div>
    );
  }

  if (variant === "line") {
    return (
      <div className="animate-pulse" style={{ height }}>
        <div className="flex items-end gap-1 h-full px-2 pb-6 pt-4">
          {Array.from({ length: 12 }).map((_, i) => {
            const pct = 30 + Math.sin(i * 0.6) * 25 + (i % 3) * 8;
            return (
              <div
                key={i}
                className="flex-1 rounded-sm bg-zinc-700/40"
                style={{ height: `${Math.max(10, pct)}%` }}
              />
            );
          })}
        </div>
      </div>
    );
  }

  // bar skeleton — horizontal bars of varying widths
  return (
    <div className="animate-pulse flex flex-col gap-2 py-2" style={{ height }}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="w-20 h-3 rounded bg-zinc-700/30 flex-shrink-0" />
          <div
            className="h-4 rounded bg-zinc-700/40"
            style={{ width: `${30 + (i % 4) * 15}%` }}
          />
        </div>
      ))}
    </div>
  );
}
