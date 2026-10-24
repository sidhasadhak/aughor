"use client";

/**
 * An entity's panel, read first — laid out as the approved mockup lays it out (`design-mockups/ontology-tab.html`,
 * 2026-10-10: "one panel that did not end" became one panel and six tabs; the law is `aughor-v2/CLARITY.md`).
 *
 * The four figures under the name; what needs a person, in amber, with its buttons on the row; each process the entity
 * goes through as a funnel — stage · bar · count — with every promise on one line and its overdue count a button; the
 * sets it is read in; and what uses it. Everything here is what the panel already reads (`GET /object-types/{type}`)
 * and what the process panel reads (`GET /ontology/processes`): nothing is counted afresh, and a figure the data did not
 * give is not drawn.
 */
import React from "react";

import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Badge } from "@/components/ui/badge";
import { countNoun, formatCount, formatMonth, pct } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import type { ObjectTypeDetail, ObjectTypeUses, ProcessDetail, ProcessPromise, ProcessesAndRules } from "@/lib/objectTypes";

const muted: React.CSSProperties = { color: "var(--t3)" };
const tabular: React.CSSProperties = { fontVariantNumeric: "tabular-nums" };

/** A section's small uppercase label, with what it says at its right end. */
export function Label({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, color: "var(--t3)",
                                        textTransform: "uppercase", letterSpacing: ".06em" }}>
      {children}
      {right && <span style={{ marginLeft: "auto", textTransform: "none", letterSpacing: 0 }}>{right}</span>}
    </div>
  );
}

/** "Order" → "orders": the noun an entity's count reads in. */
export function pluralOf(name: string): string {
  const word = name.trim().toLowerCase();
  if (!word) return "objects";
  if (/(s|x|z|ch|sh)$/.test(word)) return `${word}es`;
  if (/[^aeiou]y$/.test(word)) return `${word.slice(0, -1)}ies`;
  return `${word}s`;
}

/** "late_dispatch" → "Late dispatch": a declared name in the reader's words. */
export function humanName(id: string): string {
  const words = id.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : id;
}

function Figure({ value, label, tone, title, testid, word = false }: {
  value: React.ReactNode; label: string; tone?: string; title?: string; testid?: string;
  /** A name rather than a number (the key's column): set smaller, so a name like order_id is read whole. */
  word?: boolean;
}) {
  return (
    <div style={{ background: "var(--bg-2)", borderRadius: "var(--r2)", padding: "7px 10px", minWidth: 0 }} title={title}
      data-testid={testid}>
      <div className={word ? "aug-fs-sm" : "aug-fs-h2"} style={{ ...tabular, color: tone ?? "var(--t1)", fontWeight: 600, overflow: "hidden",
                                          lineHeight: word ? "22px" : undefined,
                                          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {value}
      </div>
      <div className="aug-fs-xs" style={muted}>{label}</div>
    </div>
  );
}

/** The four figures under an entity's name: its objects, its key, its properties, its links. */
export function TypeFigures({ detail }: { detail: ObjectTypeDetail }) {
  const { key, counts } = detail;
  const parts = counts.parts ?? detail.parts?.length ?? 0;
  const objects = detail.platform
    ? { value: "in Aughor", label: "kept by actions", title: "Its objects live in Aughor's edit layer — nothing is counted on a warehouse" }
    : key.rows == null
      ? { value: "—", label: `${pluralOf(detail.display_name)}, not counted`, title: "its rows are not counted yet" }
      : { value: formatCount(key.rows), label: pluralOf(detail.display_name), title: `${formatCount(key.rows)} rows` };
  const keyFig = key.verified === true
    ? { tone: "var(--grn4)", label: "key, unique", mark: "✓ " }
    : key.verified === false
      ? { tone: "var(--red4)", label: "key, not unique", mark: "" }
      : { tone: "var(--t2)", label: "key, not counted", mark: "" };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 6, marginTop: 12 }}
      data-testid="entity-figures">
      <Figure value={objects.value} label={objects.label} title={objects.title} testid="entity-figure-objects" />
      <Figure value={<span style={{ fontFamily: "var(--font-mono)" }}>{keyFig.mark}{key.property}</span>} label={keyFig.label}
        tone={keyFig.tone} title={key.note || key.property} testid="entity-figure-key" word />
      <Figure value={formatCount(counts.properties)} label={counts.properties === 1 ? "property" : "properties"}
        testid="entity-figure-properties" />
      <Figure value={formatCount(counts.links)}
        label={`${counts.links === 1 ? "link" : "links"}${parts ? ` · ${countNoun(parts, "part")}` : ""}`}
        testid="entity-figure-links" />
    </div>
  );
}

/** One thing that waits on a person: what it is, one muted line, and its buttons on the row. */
export function NeedsRow({ title, detail, children, testid }: {
  title: React.ReactNode; detail?: React.ReactNode; children?: React.ReactNode; testid?: string;
}) {
  return (
    <div data-testid={testid ?? "entity-needs"}
      style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "8px 10px", borderRadius: "var(--r2)",
               background: "var(--amb1)" }}>
      <span style={{ flex: "1 1 160px", minWidth: 0 }}>
        <span className="aug-fs-sm" style={{ display: "block", color: "var(--t1)" }}>{title}</span>
        {detail && <span className="aug-fs-xs" style={{ display: "block", color: "var(--t2)" }}>{detail}</span>}
      </span>
      {children}
    </div>
  );
}

/** A promise in the reader's words: "Dispatch within 2 days". */
export function promiseWords(p: ProcessPromise): string {
  const name = humanName(p.name);
  if (p.kind === "deadline") return `${name} by ${p.deadline}`;
  if (p.kind === "within_hours") return `${name} within ${p.within_hours} hour${p.within_hours === 1 ? "" : "s"}`;
  return `${name} within ${p.within_days} day${p.within_days === 1 ? "" : "s"}`;
}

/** A process an entity goes through, as a funnel: each stage, a bar of the objects that reached it, and the count; then
 *  every promise on one line — what it promises, how often it is broken, and how many objects are already past it, which
 *  opens the process. A process the data refuted says so above its funnel. */
export function ProcessFlow({ process, onOpenProcess }: {
  process: ProcessDetail;
  onOpenProcess?: (processId: string) => void;
}) {
  const left = process.leaves?.left;
  const promises = process.stages.filter((s) => s.promise).map((s) => ({ stage: s.name, promise: s.promise! }));
  return (
    <div data-testid="process-flow">
      <Label right={left != null && process.leaves ? (
        <span style={muted} title={process.leaves.note}>
          {formatCount(left)} left · {process.leaves.values.join(", ").toLowerCase()}
        </span>
      ) : undefined}>
        {process.display_name}
      </Label>
      {process.verified === false && (
        <p className="aug-fs-xs" style={{ margin: "0 0 6px", color: "var(--red4)" }}>{process.note || "measured false"}</p>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "72px minmax(0, 1fr) 72px", gap: "5px 10px", alignItems: "center" }}>
        {withUniqueKeys(process.stages, (s) => s.name).map(([key, s]) => (
          <React.Fragment key={key}>
            <span className="aug-fs-sm" style={{ color: "var(--t1)", overflow: "hidden", textOverflow: "ellipsis",
                                                 whiteSpace: "nowrap" }} title={s.note}>
              {s.display_name}
            </span>
            <span style={{ height: 10, borderRadius: 5, background: "var(--bg-3)", overflow: "hidden" }} aria-hidden>
              {s.share != null && (
                <span data-testid="process-flow-bar"
                  style={{ display: "block", height: "100%", borderRadius: 5, background: "var(--chart-1)",
                           width: `${Math.max(0, Math.min(1, s.share)) * 100}%` }} />
              )}
            </span>
            <span className="aug-fs-sm" data-testid="process-flow-count"
              style={{ ...tabular, textAlign: "right", color: s.reached == null ? "var(--t3)" : "var(--t2)" }}
              title={s.reached == null ? "not counted" : undefined}>
              {s.reached == null ? "—" : formatCount(s.reached)}
            </span>
          </React.Fragment>
        ))}
      </div>
      {promises.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 12 }}>
          {withUniqueKeys(promises, (p) => `${p.stage}:${p.promise.name}`).map(([key, { promise: p }]) => (
            <PromiseLine key={key} promise={p} processId={process.id} onOpenProcess={onOpenProcess} />
          ))}
        </div>
      )}
    </div>
  );
}

function PromiseLine({ promise: p, processId, onOpenProcess }: {
  promise: ProcessPromise; processId: string; onOpenProcess?: (processId: string) => void;
}) {
  const counted = p.verified !== null && p.breach_rate != null;
  return (
    <div data-testid="process-flow-promise" title={p.note}
      style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto auto", gap: "8px 12px", alignItems: "center",
               padding: "7px 10px", background: "var(--bg-2)", borderRadius: "var(--r2)" }}>
      <span className="aug-fs-sm" style={{ color: "var(--t1)" }}>{promiseWords(p)}</span>
      <span className="aug-fs-sm" style={{ ...tabular, color: counted ? "var(--amb4)" : "var(--t3)" }}>
        {counted ? `broken ${pct(p.breach_rate, 1)}` : "not counted yet"}
      </span>
      {p.open_overdue != null && p.open_overdue > 0 ? (
        <Button variant="outline" size="xs" disabled={!onOpenProcess} onClick={() => onOpenProcess?.(processId)}
          data-testid="process-flow-overdue"
          title={`${formatCount(p.open_overdue)} not reached yet and already past the promise${p.as_of ? ` as of ${p.as_of}` : ""} — open the process`}>
          {formatCount(p.open_overdue)} overdue
        </Button>
      ) : (
        <Button variant="ghost" size="xs" disabled={!onOpenProcess} onClick={() => onOpenProcess?.(processId)}
          title="Open the process — its stages, timings and promises">
          Open
        </Button>
      )}
    </div>
  );
}

/** The sets an entity is read in — its segments and those its processes and rules derive — each with the count the data
 *  gave it where it gave one: a rule's admitted objects, a promise's broken ones, its overdue ones. */
export function SetChips({ detail, scope }: { detail: ObjectTypeDetail; scope: ProcessesAndRules | null }) {
  const derived = detail.derived?.segments ?? [];
  const names = [...new Set([...derived.map((d) => d.name), ...detail.segments])];
  if (!names.length) return null;
  const counts = new Map<string, number>();
  for (const rule of scope?.rules ?? []) if (rule.segment && rule.admitted != null) counts.set(rule.segment, rule.admitted);
  for (const p of scope?.processes ?? []) {
    for (const s of p.stages) {
      const promise = s.promise;
      if (!promise || promise.verified === null) continue;          // a promise not counted yet gives no count
      if (promise.segment && promise.breached != null) counts.set(promise.segment, promise.breached);
      if (promise.overdue_segment && promise.open_overdue != null) counts.set(promise.overdue_segment, promise.open_overdue);
    }
  }
  const said = new Map(derived.map((d) => [d.name, d]));
  return (
    <div>
      <Label>Sets</Label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }} data-testid="entity-sets">
        {names.map((name) => {
          const d = said.get(name);
          const n = counts.get(name);
          return (
            <span key={`set:${name}`} className="aug-fs-xs" data-testid="entity-set"
              title={d ? (d.usable ? d.description : `refused: ${d.why_not ?? ""}`) : `a segment of ${detail.display_name}`}
              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "2px 8px", borderRadius: "var(--r-pill)",
                       background: "var(--bg-3)", border: "1px solid var(--b1)", whiteSpace: "nowrap",
                       color: d && !d.usable ? "var(--t3)" : "var(--t2)" }}>
              {humanName(name)}
              {n != null && <span style={{ ...tabular, color: "var(--t1)" }}>{formatCount(n)}</span>}
              {d && !d.usable && <span style={{ color: "var(--red4)" }}>refused</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** What uses an entity: its verified metrics and the declared actions that take it — each opens the tab that holds it. */
export function UsedBy({ detail, onMetric, onAction }: {
  detail: ObjectTypeDetail; onMetric: () => void; onAction: () => void;
}) {
  if (!detail.metrics.length && !detail.actions.length) return null;
  return (
    <div>
      <Label>Used by</Label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }} data-testid="entity-used-by">
        {detail.metrics.map((m) => (
          <Button key={`metric:${m.id}`} variant="ghost" size="xs" onClick={onMetric} title={m.formula_sql}
            style={{ background: "var(--blue1)", color: "var(--blue4)" }}>
            Metric · {humanName(m.display_name || m.id)}
          </Button>
        ))}
        {detail.actions.map((a) => (
          <Button key={`action:${a.id}`} variant="outline" size="xs" onClick={onAction} title={a.description || a.why}>
            <Icon name="bolt" size={12} /> {a.display_name}
          </Button>
        ))}
      </div>
    </div>
  );
}

/** The dependents the section groups, in the order they are shown, with the noun each takes. Metrics and declared
 *  actions are not here: `UsedBy` above already lists them, and a thing is said once. */
const CONSUMERS: [string, string, string][] = [
  ["automation", "automation", "automations"], ["process", "process", "processes"], ["rule", "rule", "rules"],
  ["link", "link", "links"], ["part", "part", "parts"],
];

function UsesRow({ word, children }: { word: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6 }}>
      <span className="aug-fs-xs" style={{ color: "var(--t3)", minWidth: 96 }}>{word}</span>
      {children}
    </div>
  );
}

/** ROADMAP §6 item 53 — what else depends on an entity, from one door behind `ontology.entity_usage`: the dashboards
 *  whose pieces read it, its dependents by kind, each saying how on hover, and how many audited statements named its
 *  tables in each of the last twelve months — a row per month, the count beside its bar. What could not be read says
 *  so in the same place. */
export function UsesSection({ uses }: { uses: ObjectTypeUses }) {
  const groups = CONSUMERS
    .map(([kind, one, many]) => ({ kind, one, many, rows: uses.dependents.filter((d) => d.consumer === kind) }))
    .filter((g) => g.rows.length > 0);
  const nothing = !uses.dashboards.length && !groups.length;
  const months = uses.reads.months;
  const most = months.reduce((n, m) => Math.max(n, m.reads), 0);
  const total = months.reduce((n, m) => n + m.reads, 0);
  return (
    <div data-testid="entity-uses" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <Label>Depends on it</Label>
      {uses.dashboards.length > 0 && (
        <UsesRow word={countNoun(uses.dashboards.length, "dashboard")}>
          {withUniqueKeys(uses.dashboards, (d) => d.id).map(([key, d]) => (
            <Badge key={key} variant="secondary" title={`reads it in ${countNoun(d.pieces.length, "piece")}`}>{d.title || d.id}</Badge>
          ))}
        </UsesRow>
      )}
      {uses.dashboards_said && (
        <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)" }}>{uses.dashboards_said}</p>
      )}
      {withUniqueKeys(groups, (g) => g.kind).map(([groupKey, g]) => (
        <UsesRow key={groupKey} word={countNoun(g.rows.length, g.one, g.many)}>
          {withUniqueKeys(g.rows, (d) => d.id).map(([key, d]) => (
            <Badge key={key} variant="secondary" title={d.how}>{d.name}</Badge>
          ))}
        </UsesRow>
      ))}
      {nothing && (
        <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t3)" }}>
          No dashboard, automation, process or rule depends on it yet.
        </p>
      )}
      <Label right={uses.reads.tables.length > 0 && (
        <span className="aug-fs-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--t3)" }}>
          {uses.reads.tables.join(" · ")}
        </span>
      )}>
        Reads · 12 months
      </Label>
      {uses.reads.said ? (
        <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)" }}>{uses.reads.said}</p>
      ) : total === 0 ? (
        <p className="aug-fs-xs" style={{ margin: 0, color: "var(--t3)" }}>
          No statement named its tables in the last 12 months.
        </p>
      ) : (
        <div data-testid="entity-reads" style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr) auto",
                                                 gap: "4px 10px", alignItems: "center" }}>
          {months.map((m) => (
            <React.Fragment key={m.month}>
              <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{formatMonth(m.month)}</span>
              <div style={{ height: 6, background: "var(--bg-3)", borderRadius: 3, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${most ? (m.reads / most) * 100 : 0}%`, background: "var(--blue3)" }} />
              </div>
              <span className="aug-fs-xs" style={{ ...tabular, color: "var(--t2)" }}>{formatCount(m.reads)}</span>
            </React.Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
