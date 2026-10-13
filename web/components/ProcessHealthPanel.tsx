"use client";

/**
 * Health — every metric that has a target, scored against it, laid out to CLARITY (`aughor-v2/CLARITY.md`): four
 * figures (on target, warning, off target, not computed), the metrics off target or at a warning in amber with a way
 * to ask why on the row, then the rest. Each metric is said once.
 *
 * The scorecard runs each targeted metric's governed query on the warehouse, so it is read once per visit (and on
 * Retry) — never polled. With no metric targeted it says so in one line and opens the place a target is set: a
 * metric's Edit tab in the Semantic Layer.
 */
import { useEffect, useState, type ReactNode } from "react";

import { CARD, Chip, Dot, Empty, Figure, Figures, Label, MUTED, NUM, NeedsYou, ONE_LINE, Page, ROW, RULE, type Tone }
  from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import { getHealthScorecard, type HealthStatus, type ScorecardItem } from "@/lib/api";
import { compactNumber, countNoun, formatCount, formatMetricValue, formatPercent, formatVariance } from "@/lib/format";
import { unitKind } from "@/lib/home";
import { withUniqueKeys } from "@/lib/listKeys";

/** A status as a mark: its word, its hue, the tone of its variance chip. */
const MARK: Record<HealthStatus, { word: string; hue: "green" | "amber" | "red" | "grey"; tone: Tone }> = {
  red: { word: "off target", hue: "red", tone: "down" },
  yellow: { word: "warning", hue: "amber", tone: "amber" },
  unknown: { word: "not computed", hue: "grey", tone: "plain" },
  green: { word: "on target", hue: "green", tone: "up" },
};
const STATUS_TEXT: Record<HealthStatus, string> = {
  red: "var(--red4)", yellow: "var(--amb4)", unknown: "var(--t3)", green: "var(--grn4)",
};
const ORDER: HealthStatus[] = ["red", "yellow", "unknown", "green"];

/** A metric's value as a reader reads it, by what its unit says: money short ($231.5K), a share as a percent (60.0%),
 *  days as days, anything else compact with its unit after it. */
export function valueText(v: number, unit: string | null): string {
  const kind = unitKind(unit ?? undefined);
  if (kind === "money") return `${v < 0 ? "-" : ""}$${compactNumber(Math.abs(v), Math.abs(v) >= 1000 ? 1 : 2)}`;
  if (kind === "percent" || kind === "ratio") return formatPercent(v, 1);
  if (kind === "days") return `${v.toFixed(1)} days`;
  // 4.48M · 45.3K · 1,904
  const n = Math.abs(v) >= 1e4 && Math.abs(v) < 1e6 ? compactNumber(v, 1) : formatMetricValue(v);
  return unit && kind === "number" ? `${n} ${unit}` : n;
}

export function ProcessHealthPanel({ connectionId, onAsk, onOpenMetrics }: {
  connectionId: string;
  /** Opens a chat and asks the question straight away. */
  onAsk: (question: string) => void;
  /** Opens the Semantic Layer's Metrics, where a metric's target is set (its Edit tab). */
  onOpenMetrics?: () => void;
}) {
  const [items, setItems] = useState<ScorecardItem[] | null>(null);
  // A failed read used to read as "No health metrics configured" — telling a person to go and define metrics that may
  // well exist. It says what failed now.
  const [failed, setFailed] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    if (!connectionId) return;
    let alive = true;
    setItems(null);
    setFailed(null);
    getHealthScorecard(connectionId)
      .then(list => { if (alive) setItems(list); })
      .catch(e => { if (alive) setFailed(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [connectionId, reload]);

  if (!connectionId) {
    return <Page testId="health"><div className="aug-fs-sm" style={{ ...CARD, ...MUTED }}>Choose a connection to score its metrics.</div></Page>;
  }
  if (failed !== null) {
    return <Page testId="health"><ReadFailed what="the scorecard" error={failed} onRetry={() => setReload(n => n + 1)} style={CARD} /></Page>;
  }
  if (items === null) {
    return <Page testId="health"><Loading what="the scorecard (it runs each metric's query)" style={CARD} /></Page>;
  }

  if (items.length === 0) {
    return (
      <Page testId="health">
        <section aria-label="Scorecard" data-testid="health-empty" style={CARD}>
          <Label>Scorecard</Label>
          <Empty>No metric has a target yet, so nothing is scored.</Empty>
          <div style={{ ...ROW, marginTop: 8 }}>
            {onOpenMetrics && <Button size="xs" variant="secondary" onClick={onOpenMetrics}>Set a target</Button>}
            <Chip title="In the Semantic Layer's Metrics, open a metric, then its Edit tab: Target value, Warning and Critical">
              Semantic Layer › a metric › Edit
            </Chip>
          </div>
        </section>
      </Page>
    );
  }

  const count = (s: HealthStatus) => items.filter(i => i.status === s).length;
  const sorted = [...items].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status) || a.label.localeCompare(b.label));
  const attention = sorted.filter(i => i.status === "red" || i.status === "yellow");
  const rest = sorted.filter(i => i.status === "green" || i.status === "unknown");
  const ask = (label: string) => onAsk(`Why is ${label} off target? Find the root cause and the contributing factors.`);

  return (
    <Page testId="health">
      <Figures testId="health-figures">
        <Figure testId="health-fig-green" label="On target" value={formatCount(count("green"))}
          sub={`of ${countNoun(items.length, "metric")} with a target`} />
        <Figure testId="health-fig-yellow" label="Warning" value={formatCount(count("yellow"))}
          tone={count("yellow") ? "amber" : undefined} sub="past the warning line" />
        <Figure testId="health-fig-red" label="Off target" value={formatCount(count("red"))}
          tone={count("red") ? "red" : undefined} sub="past the critical line" />
        <Figure testId="health-fig-unknown" label="Not computed" value={formatCount(count("unknown"))}
          sub={count("unknown") ? "its query failed or returned nothing" : "every one computed"} />
      </Figures>

      {attention.length > 0 && (
        <NeedsYou testId="health-needs" right={countNoun(attention.length, "metric")}>
          {withUniqueKeys(attention, m => m.name).map(([key, m], i) => (
            <MetricRow key={key} m={m} first={i === 0}
              action={<Button size="xs" variant="secondary" title="Asks it in a chat" onClick={() => ask(m.label)}>Ask why</Button>} />
          ))}
        </NeedsYou>
      )}

      {rest.length > 0 && (
        <section aria-label="Scorecard" data-testid="health-list" style={CARD}>
          <Label right={[count("green") && `${formatCount(count("green"))} on target`,
            count("unknown") && `${formatCount(count("unknown"))} not computed`].filter(Boolean).join(" · ")}>
            Scorecard
          </Label>
          {withUniqueKeys(rest, m => m.name).map(([key, m], i) => <MetricRow key={key} m={m} first={i === 0} />)}
        </section>
      )}
    </Page>
  );
}

/** One metric: its name (period and benchmark under it), its value against the target, the variance, the status. */
function MetricRow({ m, first, action }: { m: ScorecardItem; first: boolean; action?: ReactNode }) {
  const mark = MARK[m.status];
  const meta = [m.target_period, m.benchmark_source].filter(Boolean).join(" · ");
  return (
    <div data-testid="health-row" style={{ display: "grid", alignItems: "center", gap: 12, padding: "7px 0",
      gridTemplateColumns: "12px minmax(0, 1fr) auto auto", ...(first ? {} : RULE) }}>
      <Dot hue={mark.hue} title={mark.word} />
      <div style={{ minWidth: 0 }}>
        <div className="aug-fs-chrome" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }} title={m.label}>{m.label}</div>
        {meta && <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }} title={meta}>{meta}</div>}
      </div>
      <div style={{ ...ROW, flexWrap: "nowrap", gap: 8, justifyContent: "flex-end" }}>
        {m.current !== null
          ? <span className="aug-fs-chrome" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>{valueText(m.current, m.unit)}</span>
          : <Chip title="The metric's query failed or returned no value, so it was not scored">no value</Chip>}
        {m.target !== null && (
          <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, whiteSpace: "nowrap" }}>vs {valueText(m.target, m.unit)}</span>
        )}
        {m.variance !== null && (
          <Chip tone={mark.tone} title={`${formatVariance(m.variance)} against its target`}>{formatVariance(m.variance)}</Chip>
        )}
      </div>
      <div style={{ ...ROW, flexWrap: "nowrap", justifyContent: "flex-end", minWidth: 84 }}>
        <span className="aug-fs-xs" style={{ whiteSpace: "nowrap", color: STATUS_TEXT[m.status] }}>{mark.word}</span>
        {action}
      </div>
    </div>
  );
}
