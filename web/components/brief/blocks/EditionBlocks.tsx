"use client";

/**
 * Arc BC (ROADMAP §3.67) — an edition drawn from the blocks the model composed.
 *
 * The model chose each block's type and words; this file draws them, and only from the sources the server ran:
 * a sentence's cited numbers open their source, a chart reads its source's rows, a control fades the rows of every
 * other value in the blocks that listen to it, a drill asks the server for one level deeper. A block of a type this
 * page does not know is said, never silently skipped.
 */
import { useEffect, useMemo, useState } from "react";

import { Bridge, LineMark, Multiples, PairRows, ProgressBars, RangeBars } from "@/components/brief/EditionFigure";
import { VegaChart } from "@/components/charts/vega/VegaChart";
import { TableActions, rawCells } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Segmented } from "@/components/ui/segmented";
import type { EditionBlock, EditionFigure, EditionSource } from "@/lib/api";
import { bridgeSteps, drillOptions, fmtChange, fmtValue, parseCited } from "@/lib/briefingEdition";
import { withUniqueKeys } from "@/lib/listKeys";
import { getObjectCatalog } from "@/lib/objects";
import { objectHref, objectKeyColumns } from "@/lib/objectLinks";

export const BLOCK_TYPES = ["lead", "figure", "bridge", "compare", "table", "map", "multiples", "heat", "progress",
                            "line", "control", "decision", "quiet"] as const;
type BlockType = typeof BLOCK_TYPES[number];

const MONEY_COL = /(eur|usd|gbp|gmv|revenue|sales|amount|value|price|cost|refund|spend)/i;
const RULE = "1px solid var(--b1)";

interface Ctx {
  sources: Record<string, EditionSource>;
  figures: Record<string, EditionFigure>;
  drillColumns?: Record<string, string[]>;
  controls: Record<string, string>;
  controlBlocks: Record<string, EditionBlock>;
  setControl: (id: string, v: string) => void;
  currency: string;
  connectionId: string;
  schema?: string;
  keyTypes: Map<string, string>;
  onCite: (sourceId: string) => void;
  onDrill: (block: EditionBlock, column: string, segment?: unknown) => void;
  onDecide: (action: string, block: EditionBlock) => void;
  drilling: string;
}

/** Words with their cited numbers as buttons that open the source. */
export function CitedText({ text, onCite }: { text?: string; onCite: (s: string) => void }) {
  return (
    <>
      {withUniqueKeys(parseCited(text), r => r.text).map(([key, r]) => r.source
        ? <span key={key} role="button" tabIndex={0} className="aug-why" data-source={r.source}
            style={{ color: "var(--t1)", borderBottom: "1px dotted var(--t3)", cursor: "pointer" }}
            onClick={() => onCite(r.source as string)}
            onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onCite(r.source as string); } }}>
            {r.text}
          </span>
        : <span key={key}>{r.text}</span>)}
    </>
  );
}

const col = (src: EditionSource, name?: string) => (name ? src.columns.indexOf(name) : -1);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const word = (v: unknown) => (v === true ? "Yes" : v === false ? "No" : v === null || v === undefined ? "—" : String(v));

function fmtFor(src: EditionSource, column: string | undefined, currency: string) {
  const unit = src.unit || (column && MONEY_COL.test(column) ? currency : "");
  return (v: unknown) => fmtValue(v, unit);
}

/** The value a listening block's row holds for a control's column, to fade it when another value is chosen. */
function fadeOf(block: EditionBlock, src: EditionSource, ctx: Ctx): ((row: unknown[]) => boolean) | undefined {
  const ctrl = block.listens ? ctx.controlBlocks[block.listens] : undefined;
  const chosen = block.listens ? ctx.controls[block.listens] : undefined;
  if (!ctrl || !chosen || chosen === "All") return undefined;
  const i = col(src, ctrl.column);
  return i < 0 ? undefined : row => word(row[i]) !== chosen;
}

/** A comparison's rows: a breakdown's segments against their usual, or any label/value/compare columns. */
function pairRows(block: EditionBlock, src: EditionSource) {
  const breakdown = src.kind === "breakdown" || src.kind === "drill";
  const li = col(src, block.label || (breakdown ? "segment" : undefined));
  const vi = col(src, block.value || (breakdown ? "this_range" : undefined));
  const ci = col(src, block.compare || (breakdown ? "usual" : undefined));
  const ti = col(src, breakdown ? "too_few" : undefined);
  return src.rows.map(r => ({ row: r, label: word(r[li]), now: num(r[vi]), base: ci >= 0 ? num(r[ci]) : null,
                              thin: ti >= 0 ? r[ti] === true : false }));
}

type BodyProps = { block: EditionBlock; src?: EditionSource; ctx: Ctx };

function Missing({ what }: { what: string }) {
  return <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: 0 }}>{what}</p>;
}

const BODY: Record<BlockType, (p: BodyProps) => React.ReactNode> = {
  lead: ({ block, ctx }) => (
    <>
      <p data-testid="edition-lead" className="aug-fs-display" style={{ color: "var(--t1)", fontWeight: 600, lineHeight: 1.28,
                                                                        maxWidth: "32ch", margin: "4px 0 10px" }}>
        <CitedText text={block.text} onCite={ctx.onCite} />
      </p>
      {block.sub && <p className="aug-fs-h2" style={{ maxWidth: "66ch", margin: 0, lineHeight: 1.55 }}>
        <CitedText text={block.sub} onCite={ctx.onCite} /></p>}
    </>
  ),
  figure: ({ block, src, ctx }) => {
    const fig = src ? ctx.figures[src.id] : undefined;
    if (!src || !fig) return <Missing what="This figure's measurement is not in the edition." />;
    const u = fig.usual;
    return (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1.3fr)", gap: 22, alignItems: "center" }}>
        <div>
          <div className="aug-fs-display" style={{ color: "var(--t1)", fontWeight: 600 }}>{fig.current_text}</div>
          {u && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>usual {u.low_text}–{u.high_text}</div>}
          {fig.previous_text && <div className="aug-fs-sm" style={{ color: "var(--t3)" }}>the range before {fig.previous_text}</div>}
          {block.text && <p className="aug-fs-sm" style={{ margin: "8px 0 0" }}><CitedText text={block.text} onCite={ctx.onCite} /></p>}
        </div>
        <RangeBars figure={fig} period="week" />
      </div>
    );
  },
  bridge: ({ block, src, ctx }) => {
    const steps = bridgeSteps(block, ctx.sources);
    if (!steps.length) return <Missing what="This bridge's steps could not be read from its source." />;
    const unit = src?.unit || (block.chain?.[0] ? ctx.sources[block.chain[0]]?.unit : "") || ctx.currency;
    return <Bridge steps={steps} fmt={v => fmtValue(v, unit)} />;
  },
  compare: ({ block, src, ctx }) => {
    if (!src) return null;
    const rows = pairRows(block, src);
    const fade = fadeOf(block, src, ctx);
    const fmt = fmtFor(src, block.value, ctx.currency);
    return <PairRows rows={rows} better={src.better} fmt={v => fmt(v)}
      change={(a, b) => fmtChange(a, b, src.unit)} dim={fade ? label => fade(rows.find(r => r.label === label)?.row ?? []) : undefined} />;
  },
  table: ({ block, src, ctx }) => {
    if (!src) return null;
    const shown = (block.columns?.length ? block.columns : src.columns).filter(c => src.columns.includes(c));
    const idx = shown.map(c => src.columns.indexOf(c));
    const fade = fadeOf(block, src, ctx);
    const linkType = block.link ? ctx.keyTypes.get(block.link.toLowerCase()) : undefined;
    return (
      <div>
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <TableActions name={block.title || src.label}
            read={() => ({ columns: shown, rows: rawCells(src.rows.map(r => idx.map(i => r[i]))) })} />
        </div>
        <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead><tr>{shown.map(c => <th key={c} style={{ textAlign: "left", fontWeight: 500, color: "var(--t3)", padding: "6px 8px", borderBottom: RULE }}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
          <tbody>
            {src.rows.map((r, ri) => (
              <tr key={`${ri}-${String(r[0])}`} style={{ opacity: fade?.(r) ? 0.35 : 1 }} data-faded={fade?.(r) ? "true" : undefined}>
                {idx.map((i, j) => {
                  const v = r[i];
                  const isLink = linkType && shown[j] === block.link && v !== null && v !== undefined;
                  return (
                    <td key={shown[j]} style={{ padding: "7px 8px", borderBottom: RULE, textAlign: typeof v === "number" ? "right" : "left",
                                                color: typeof v === "number" ? "var(--t1)" : undefined }}>
                      {isLink ? <a href={objectHref(linkType as string, String(v), ctx.connectionId, ctx.schema)} style={{ color: "var(--blue4)" }}>{String(v)}</a>
                        : typeof v === "number" ? fmtFor(src, shown[j], ctx.currency)(v) : word(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  },
  map: ({ block, src, ctx }) => {
    if (!src) return null;
    const rows = pairRows(block, src).filter(r => r.now !== null);
    const values = rows.map(r => ({ place: r.label, now: r.now, change: r.base ? (r.now as number) / r.base - 1 : null }));
    const ranked = [...rows].sort((a, b) => ((b.base ? (b.now as number) / b.base : 0) - (a.base ? (a.now as number) / a.base : 0)));
    const fmt = fmtFor(src, block.value, ctx.currency);
    const spec = {
      data: { url: "/geo/world.json", format: { property: "features" } },
      projection: { type: "equalEarth" },
      transform: [{ lookup: "properties.name", from: { data: { values }, key: "place", fields: ["change", "now"] } }],
      mark: { type: "geoshape", tooltip: true },
      encoding: { color: { field: "change", type: "quantitative", scale: { range: "diverging", domainMid: 0 },
                           legend: { title: "change against usual", format: "+.0%" } } },
    };
    return (
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.6fr) minmax(0,1fr)", gap: 20, alignItems: "center" }}>
        <div data-testid="edition-map"><VegaChart spec={spec} height={300} /></div>
        <PairRows rows={[...ranked.slice(0, 5), ...ranked.slice(-2)].filter((r, i, a) => a.indexOf(r) === i)} better={src.better || "up"}
          fmt={v => fmt(v)} change={(a, b) => fmtChange(a, b, "")} />
      </div>
    );
  },
  multiples: ({ block, src, ctx }) => {
    if (!src) return null;
    const [xi, si, vi] = [col(src, block.x), col(src, block.series), col(src, block.value)];
    const by = new Map<string, { x: string; v: number }[]>();
    src.rows.forEach(r => { const v = num(r[vi]); if (v === null) return; const k = word(r[si]); by.set(k, [...(by.get(k) ?? []), { x: String(r[xi]), v }]); });
    const series = [...by.entries()].map(([name, points]) => ({ name, points: points.sort((a, b) => a.x.localeCompare(b.x)) }));
    return <Multiples series={series} fmt={v => fmtFor(src, block.value, ctx.currency)(v)} />;
  },
  heat: ({ block, src, ctx }) => {
    if (!src) return null;
    const [li, si, vi, ci] = [col(src, block.label), col(src, block.series), col(src, block.value), col(src, block.compare)];
    const rowsOf = [...new Set(src.rows.map(r => word(r[li])))];
    const colsOf = [...new Set(src.rows.map(r => word(r[si])))];
    const cell = (a: string, b: string) => src.rows.find(r => word(r[li]) === a && word(r[si]) === b);
    return (
      <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "collapse" }} data-testid="edition-heat">
        <thead><tr><th />{colsOf.map(c => <th key={c} style={{ fontWeight: 500, color: "var(--t3)", padding: "6px 8px" }}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
        <tbody>{rowsOf.map(a => (
          <tr key={a}><td style={{ color: "var(--t1)", padding: "8px 10px", borderTop: RULE }}>{a}</td>{colsOf.map(b => {
            const r = cell(a, b); if (!r) return <td key={b} style={{ textAlign: "center", color: "var(--t4)", borderTop: RULE }}>·</td>;
            const now = num(r[vi]), base = ci >= 0 ? num(r[ci]) : null;
            const ch = now !== null && base ? now / base - 1 : null, thin = now !== null && now < 30;
            const tint = thin || ch === null ? "transparent" : ch > 0 ? "var(--amb1)" : "var(--grn1)";
            return <td key={b} title={thin ? "under 30 — too few to call" : undefined}
              style={{ textAlign: "center", padding: "8px 10px", borderTop: RULE, background: tint, color: thin ? "var(--t3)" : "var(--t1)" }}>
              {fmtFor(src, block.value, ctx.currency)(now)} {ch !== null && <span style={{ color: "var(--t3)" }}>{fmtChange(now, base, "")}</span>}</td>;
          })}</tr>))}</tbody>
      </table>
    );
  },
  progress: ({ block, src, ctx }) => {
    if (!src) return null;
    const [li, vi] = [col(src, block.label), col(src, block.value)];
    const rows = src.rows.map(r => ({ label: word(r[li]), v: num(r[vi]) ?? 0 }));
    return <ProgressBars rows={rows} fmt={v => fmtFor(src, block.value, ctx.currency)(v)} />;
  },
  line: ({ block, src, ctx }) => {
    if (!src) return null;
    const [xi, vi] = src.kind === "check" ? [0, 1] : [col(src, block.x), col(src, block.value)];
    const points = src.rows.map(r => ({ x: String(r[xi]), v: num(r[vi]) as number })).filter(p => p.v !== null);
    return <LineMark points={points} mark={block.mark} fmt={v => fmtFor(src, block.value, ctx.currency)(v)} />;
  },
  control: ({ block, src, ctx }) => {
    if (!src) return null;
    const i = col(src, block.column);
    const values = [...new Set(src.rows.map(r => word(r[i])))].slice(0, 8);
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>{block.title || `Look at one ${block.column?.replace(/_/g, " ")}`}</span>
        <Segmented label={block.title || "Choose one"} value={ctx.controls[block.id] ?? "All"} onChange={v => ctx.setControl(block.id, v)}
          options={["All", ...values].map(v => ({ value: v, label: v }))} />
      </div>
    );
  },
  decision: ({ block, ctx }) => (
    <>
      <p className="aug-fs-h2" style={{ color: "var(--t1)", margin: 0 }}><CitedText text={block.text} onCite={ctx.onCite} /></p>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        {(block.actions?.length ? block.actions : ["investigate", "not_now"]).map(a => (
          <Button key={a} size="sm" variant={a === "investigate" ? "default" : "ghost"} onClick={() => ctx.onDecide(a, block)}>
            {a === "investigate" ? "Investigate" : "Not now"}
          </Button>
        ))}
      </div>
    </>
  ),
  quiet: ({ block, ctx }) => <p className="aug-fs-sm" style={{ color: "var(--t3)", margin: 0 }}><CitedText text={block.text} onCite={ctx.onCite} /></p>,
};

function BlockCard({ block, ctx }: { block: EditionBlock; ctx: Ctx }) {
  const src = block.source ? ctx.sources[block.source] : undefined;
  const known = (BLOCK_TYPES as readonly string[]).includes(block.type);
  const bare = block.type === "lead" || block.type === "quiet";
  const drills = drillOptions(block, ctx.sources, ctx.drillColumns);
  const decision = block.type === "decision";
  return (
    <section data-testid="edition-block" data-type={block.type}
      style={{ margin: "16px 0", padding: bare ? "4px 0" : "16px 18px", borderRadius: "var(--r3)",
               background: bare ? "transparent" : decision ? "var(--amb1)" : "var(--bg-1)",
               border: bare ? "none" : `1px solid ${block.kicker === "Drill" ? "var(--blue4)" : "var(--b1)"}` }}>
      {(block.kicker || block.title) && block.type !== "control" && (
        <>
          {block.kicker && <div className="aug-fs-xs" style={{ letterSpacing: "0.08em", textTransform: "uppercase",
                                                               color: decision ? "var(--amb4)" : "var(--t3)", marginBottom: 6 }}>{block.kicker}</div>}
          {block.title && <h3 className="aug-fs-h1" style={{ color: "var(--t1)", fontWeight: 600, margin: "0 0 8px", lineHeight: 1.3 }}>{block.title}</h3>}
        </>
      )}
      {known ? BODY[block.type as BlockType]({ block, src, ctx })
        : <Missing what={`This edition has a block of type “${block.type}”, which this page cannot draw.`} />}
      {(src || drills.length > 0) && !bare && !decision && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
          {drills.map(d => (
            <Button key={d.column} size="xs" variant="secondary" disabled={!!ctx.drilling}
              onClick={() => ctx.onDrill(block, d.column, d.segment)}>
              {ctx.drilling === `${block.id}:${d.column}` ? "Drilling…" : `By ${d.column.replace(/_/g, " ")}${d.segment !== undefined ? `, within ${word(d.segment)}` : ""}`}
            </Button>
          ))}
          {src && <span role="button" tabIndex={0} className="aug-fs-xs" style={{ marginLeft: "auto", color: "var(--t3)", cursor: "pointer", borderBottom: "1px dotted var(--t3)" }}
            onClick={() => ctx.onCite(src.id)} onKeyDown={e => { if (e.key === "Enter") ctx.onCite(src.id); }}>
            source{src.status !== "final" ? ` · ${src.status}` : ""}</span>}
        </div>
      )}
    </section>
  );
}

export function EditionBlocks({ blocks, sources, figures, drillColumns, currency, connectionId, schema, onCite, onDrill,
                                onDecide, drilling }: {
  blocks: EditionBlock[];
  sources: Record<string, EditionSource>;
  figures: EditionFigure[];
  drillColumns?: Record<string, string[]>;
  currency: string;
  connectionId: string;
  schema?: string;
  onCite: (sourceId: string) => void;
  onDrill: (block: EditionBlock, column: string, segment?: unknown) => void;
  onDecide: (action: string, block: EditionBlock) => void;
  drilling: string;
}) {
  const [controls, setControls] = useState<Record<string, string>>({});
  const [keyTypes, setKeyTypes] = useState<Map<string, string>>(new Map());
  const wantsLinks = blocks.some(b => b.type === "table" && b.link);
  useEffect(() => {
    if (!wantsLinks) return;
    let alive = true;
    getObjectCatalog(connectionId, schema).then(c => { if (alive) setKeyTypes(objectKeyColumns(c)); })
      .catch(() => { /* rows stay plain text when the catalog cannot be read */ });
    return () => { alive = false; };
  }, [wantsLinks, connectionId, schema]);
  const ctx: Ctx = useMemo(() => ({
    sources, figures: Object.fromEntries(figures.map(f => [f.id, f])), drillColumns, controls,
    controlBlocks: Object.fromEntries(blocks.filter(b => b.type === "control").map(b => [b.id, b])),
    setControl: (id, v) => setControls(c => ({ ...c, [id]: v })), currency, connectionId, schema, keyTypes,
    onCite, onDrill, onDecide, drilling,
  }), [sources, figures, drillColumns, controls, blocks, currency, connectionId, schema, keyTypes, onCite, onDrill, onDecide, drilling]);
  return <>{withUniqueKeys(blocks, b => b.id).map(([key, b]) => <BlockCard key={key} block={b} ctx={ctx} />)}</>;
}
