"use client";

/**
 * Agent Ops · Overview — where the tokens went: three short lists side by side, by model, by role and by where in the
 * code the call was made, the top three of each with the rest one click away.
 *
 * They were the Usage view of the Activity tab, which folded into the Overview (2026-10-13). They read the same
 * `/obs/usage-summary` the Overview's Model spend figure reads — one read for both, held by the Overview — so the calls
 * and the fallback share beside the spend and these lists can never disagree about the range.
 *
 * **Every ranked row is a door.** A model or a role opens the events that produced it: the Overview's Live events fold,
 * already filtered to that row (the filters W0 added to `/activity`). Before them the top-N was a dead end — the columns
 * were indexed and unreachable. A call site has no such filter, so it opens nothing rather than the whole tail.
 *
 * Names are as the data spells them: a role is the wire's word, a call site the `<module>:<function>` the provider
 * stamps on every call.
 */
import { useState, type ReactNode } from "react";

import { Card, Empty, MUTED, NUM, ONE_LINE, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Loading, ReadFailed } from "@/components/ui/states";
import type { UsageSummary } from "@/lib/api";
import { fmtMs } from "@/lib/cost";
import { compactNumber, countNoun, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

/** A drill into the live events: one model (with its provider) or one role. */
export type EventsFilter = { model?: string; provider?: string; role?: string };

/** How many rows a list shows before "all". */
export const TOP = 3;

interface Row {
  key: string;
  name: string;
  meta: ReactNode;
  value: number;
  /** A hover's word on the row: what it does not say in its line. */
  title?: string;
  onOpen?: () => void;
}

const byValue = (a: Row, b: Row) => b.value - a.value;

export function UsageLists({ data, error, onRetry, onOpenEvents }: {
  data: UsageSummary | null;
  error: string | null;
  onRetry: () => void;
  onOpenEvents: (filter: EventsFilter) => void;
}) {
  // A failed read is said where the lists would be, never drawn as three empty lists.
  if (error && !data) {
    return (
      <Card label="Where the tokens went" testId="ao-usage">
        <ReadFailed what="where the tokens went" error={error} onRetry={onRetry} />
      </Card>
    );
  }
  if (!data) {
    return <Card label="Where the tokens went" testId="ao-usage"><Loading what="where the tokens went" /></Card>;
  }

  const models: Row[] = data.models.map(m => ({
    key: `${m.provider}/${m.model}`,
    name: m.model || "(unknown)",
    meta: <>
      {m.provider || "—"} · {countNoun(m.calls, "call")}
      {m.failures > 0 && <span style={{ color: "var(--red4)" }}> · {pct(m.failure_rate)} failed</span>}
      {m.calls_without_usage > 0 && ` · ${m.calls_without_usage} without usage`}
    </>,
    value: m.total_tokens,
    title: `${fmtMs(m.mean_ms)} a call, on average`,
    onOpen: () => onOpenEvents({ model: m.model, provider: m.provider }),
  })).sort(byValue);

  const roles: Row[] = data.roles.map(r => ({
    key: r.role,
    name: r.role,
    meta: countNoun(r.calls, "call"),
    value: r.total_tokens,
    // A call that recorded no role cannot be asked for by one.
    onOpen: r.role === "(unattributed)" ? undefined : () => onOpenEvents({ role: r.role }),
  })).sort(byValue);

  const sites: Row[] = data.sites.map(s => ({
    key: s.caller,
    name: s.caller,
    meta: <>
      {countNoun(s.calls, "call")}
      {s.calls_without_usage > 0 && ` · ${s.calls_without_usage} without usage`}
    </>,
    value: s.prompt_tokens,
  })).sort(byValue);

  return (
    <div data-testid="ao-usage" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
      gap: 14 }}>
      <Short label="Where the tokens went · models" testId="ao-usage-models" rows={models}
        empty="No model calls in this range." />
      <Short label="… by role" testId="ao-usage-roles" rows={roles}
        empty="No call in this range recorded a role." />
      <Short label="… by where in the code" testId="ao-usage-sites" rows={sites} mono unit="prompt tokens"
        empty="No call in this range named where it was made." />
    </div>
  );
}

/** One list: the top three, the rest behind "all". */
function Short({ label, rows, empty, testId, mono = false, unit }: {
  label: string; rows: Row[]; empty: string; testId: string; mono?: boolean;
  /** What the figure counts, when it is not every token. */
  unit?: string;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? rows : rows.slice(0, TOP);
  return (
    <Card label={label} testId={testId} ariaLabel={label} right={<>
      {unit && <span>{unit}</span>}
      {rows.length > TOP && (
        <Button variant="link" size="xs" aria-expanded={all} onClick={() => setAll(v => !v)}>
          {all ? `top ${TOP}` : `top ${TOP} of ${rows.length} · all ›`}
        </Button>
      )}
    </>}>
      {rows.length === 0 ? <Empty>{empty}</Empty> : withUniqueKeys(shown, r => r.key).map(([key, r], i) => (
        <div key={key} data-testid={`${testId}-row`} title={r.title}
          style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", alignItems: "center", gap: 10,
            padding: "6px 0", ...(i ? RULE : {}) }}>
          <div style={{ minWidth: 0 }}>
            <div className={mono ? "aug-fs-sm aug-mono" : "aug-fs-sm"} style={{ ...ONE_LINE, color: "var(--t1)" }}>
              {r.name}
            </div>
            <div className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE }}>{r.meta}</div>
          </div>
          <span className="aug-fs-sm" style={{ ...NUM, color: "var(--t1)", fontWeight: 600 }}>{compactNumber(r.value)}</span>
          {r.onOpen ? (
            <Button variant="ghost" size="xs" onClick={r.onOpen} title={`The live events behind ${r.name}`}
              style={{ color: "var(--blue4)" }}>Explore ›</Button>
          ) : <span />}
        </div>
      ))}
    </Card>
  );
}
