"use client";

/**
 * The Metrics dashboard as a ledger (`design-mockups/metric-ledger-lux.html`; the user, 2026-11-04: "Lets move our Metrics
 * Dashboards in this manner"). One row per metric, each in its area, the industry's areas in the order its business
 * reads them: the figure, its trend against its usual range, the two comparisons, what is expected next, and one line of
 * what it means. Key movements are the same rows, most concerning first. A metric opens in its own row, never over it.
 *
 * Nothing true the figures view said is lost: each caveat stays a chip, what was not measured stays in its area with why,
 * and the expected-next bands are still booked as predictions the first time a period is read, because this table reads them.
 */
import { Fragment, useEffect, useMemo, useState, type CSSProperties } from "react";

import { rangeOf, useAskWhy, useOpenMetric, whyQuestion } from "@/components/brief/MetricDetail";
import { Chip, Dot, MUTED, NUM, NeedsRow, NeedsYou, ONE_LINE, ROW } from "@/components/clarity/kit";
import { useLoad } from "@/components/record/kit";
import { TableActions, rawCells } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/ui/segmented";
import {
  getMetricCoverage, readBriefingEdition, readExpectedNext, readMetricTrend,
  type BriefingRangeBlock, type BriefingRangeMeasure, type ExpectedNext, type MetricTrend,
} from "@/lib/api";
import {
  bandBasisWords, bandDoubt, bandWords, briefingRangeOf, changeWords, areasOf, editionFor, expectedWords, figureWords, keyMove, meaningOf, readoutOf,
  shortOf, targetWords, toneOfMove, twinsOf, workFor, type Work,
} from "@/lib/dashboards/ledger";
import { figurePeriods, ownFigures } from "@/lib/dashboards/figures";
import { countNoun, formatCount } from "@/lib/format";
import { requestTab } from "@/lib/navigate";

/** How many of a metric's ranges its trend reads: a year of months or weeks, a few years. */
const trendCount = (period: string) => (period === "year" ? 5 : 13);
/** Trends read at once: each is one warehouse statement, and a dashboard holds many metrics. */
const TRENDS_AT_ONCE = 4;

const HEAD: CSSProperties = { position: "sticky", top: 0, zIndex: 2, background: "var(--bg-1)", textAlign: "left", fontWeight: 500,
  color: "var(--t3)", padding: "7px 12px", borderBottom: "1px solid var(--b1)", whiteSpace: "nowrap" };
const CELL: CSSProperties = { padding: "5px 12px", borderBottom: "1px solid var(--b0)", verticalAlign: "middle", minWidth: 0 };
const NUMBER: CSSProperties = { ...CELL, ...NUM, textAlign: "right", whiteSpace: "nowrap" };
const HATCH = "repeating-linear-gradient(135deg, var(--bg-2) 0 6px, var(--bg-1) 6px 12px)";
const TONE: Record<string, string> = { good: "var(--grn4)", bad: "var(--red4)" };
const DOT: Record<string, string> = { good: "var(--grn4)", bad: "var(--amb4)", "": "var(--t3)" };

type Trends = Record<string, MetricTrend | undefined>;

function useTrends(connectionId: string, schema: string | undefined, block: BriefingRangeBlock) {
  const [trends, setTrends] = useState<Trends>({});
  const [done, setDone] = useState(false);
  const metrics = block.measured.map(m => m.metric).join("\n");
  useEffect(() => {
    let alive = true;
    setTrends({});
    setDone(false);
    const queue = metrics ? metrics.split("\n") : [];
    const range = rangeOf(block);
    const count = trendCount(block.period);
    const work = async () => {
      for (let metric = queue.shift(); metric !== undefined && alive; metric = queue.shift()) {
        const name = metric;
        const got = await readMetricTrend(connectionId, name, range, schema, undefined, count)
          .catch((e: unknown) => ({ metric: name, series: [], why: e instanceof Error ? e.message : String(e) }) as unknown as MetricTrend);
        if (alive) setTrends(t => ({ ...t, [name]: got }));
      }
    };
    void Promise.all(Array.from({ length: TRENDS_AT_ONCE }, work)).then(() => { if (alive) setDone(true); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- a period is its key; its object changes on every read
  }, [connectionId, schema, block.key, metrics]);
  return { trends, done };
}

/** Where a trend's points sit, the usual range included in what must fit. */
function scaleOf(values: number[], low: number | undefined, high: number | undefined) {
  const all = [...values, ...(low === undefined ? [] : [low]), ...(high === undefined ? [] : [high])];
  const lo = Math.min(...all), hi = Math.max(...all);
  const span = hi - lo || 1;
  return (v: number, top: number, bottom: number) => bottom - ((v - lo) * (bottom - top)) / span;
}

/** A row's trend: the line, its usual range as a band behind it, the newest point marked. */
function Spark({ trend, tone }: { trend: MetricTrend | undefined; tone: string }) {
  const values = (trend?.series ?? []).map(p => p.value).filter((v): v is number => typeof v === "number");
  if (values.length < 2) return null;
  const [w, h] = [72, 20];
  const y = scaleOf(values, trend?.usual?.low, trend?.usual?.high);
  const x = (i: number) => 2.5 + (i * (w - 5)) / (values.length - 1);
  const at = (v: number) => y(v, 2.5, h - 2.5);
  const u = trend?.usual;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${values.length} readings`} style={{ display: "block" }}>
      {u && <rect x={0} width={w} y={at(u.high)} height={Math.max(1, at(u.low) - at(u.high))} style={{ fill: "var(--bg-3)" }} />}
      <polyline points={values.map((v, i) => `${x(i).toFixed(1)},${at(v).toFixed(1)}`).join(" ")} fill="none" strokeWidth={1.2}
        style={{ stroke: "var(--t3)" }} />
      <circle cx={x(values.length - 1)} cy={at(values[values.length - 1])} r={2.2} style={{ fill: tone ? DOT[tone] : "var(--t1)" }} />
    </svg>
  );
}

/** A metric's trend at reading size: every point says its value on hover, the newest is labelled. */
function Trend({ m, trend, period }: { m: BriefingRangeMeasure; trend: MetricTrend; period: string }) {
  const points = trend.series.filter((p): p is typeof p & { value: number } => typeof p.value === "number");
  if (points.length < 2) return null;
  const [w, h, pad, right] = [460, 104, 10, 78];
  const inner = w - right;
  const y = scaleOf(points.map(p => p.value), trend.usual?.low, trend.usual?.high);
  const at = (v: number) => y(v, pad, h - 18);
  const x = (i: number) => pad + (i * (inner - 2 * pad)) / (points.length - 1);
  const last = points.length - 1;
  const text = (v: number) => figureWords(v, m.unit);
  const u = trend.usual;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${m.name}, ${points.length} readings`}
      style={{ display: "block", width: "100%", maxWidth: 520, height: "auto", marginBottom: 6 }}>
      {u && <rect x={pad} width={inner - 2 * pad} y={at(u.high)} height={Math.max(1, at(u.low) - at(u.high))} style={{ fill: "var(--bg-3)" }} />}
      <polyline points={points.map((p, i) => `${x(i).toFixed(1)},${at(p.value).toFixed(1)}`).join(" ")} fill="none" strokeWidth={1.6}
        style={{ stroke: "var(--chart-1)" }} />
      {points.map((p, i) => (
        <circle key={p.start} cx={x(i)} cy={at(p.value)} r={i === last ? 3.2 : 1.8} style={{ fill: "var(--chart-1)" }}>
          <title>{`${p.label}: ${text(p.value)}${p.settling ? " · still settling" : ""}`}</title>
        </circle>
      ))}
      <text x={x(last) + 8} y={at(points[last].value) + 4} fontSize={11.5} fontWeight={600} style={{ fill: "var(--t1)" }}>{text(points[last].value).replace(" days", "")}</text>
      <text x={pad} y={h - 3} fontSize={10.5} style={{ fill: "var(--t3)" }}>{shortOf(points[0].start, period)}</text>
      <text x={inner - pad} y={h - 3} fontSize={10.5} textAnchor="end" style={{ fill: "var(--t3)" }}>{shortOf(points[last].start, period)}</text>
    </svg>
  );
}

function openWork(w: Work) {
  if (w.run) requestTab("chat", { run: w.run });
  else if (w.decision) requestTab("decisions", { id: w.decision });
}

/** What a metric opens to, in its own row: how it reads, what the platform knows of it, and how it is measured. */
function Reasons({ m, trend, work, meaning, expected, block, briefed }: {
  m: BriefingRangeMeasure; trend: MetricTrend | undefined; work: Work[]; meaning: string;
  expected: ExpectedNext | null; block: BriefingRangeBlock; briefed: boolean;
}) {
  const openDetail = useOpenMetric();
  const askWhy = useAskWhy();
  const item = expected?.items.find(i => i.metric === m.metric);
  const u = trend?.usual;
  const label: CSSProperties = { ...MUTED, textTransform: "uppercase", letterSpacing: ".06em", marginBottom: 5 };
  const para: CSSProperties = { margin: "0 0 7px", color: "var(--t2)", lineHeight: 1.5, maxWidth: "62ch" };
  return (
    <div data-testid="ledger-reasons" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "14px 26px" }}>
      <div>
        <div className="aug-fs-xs" style={label}>How it is reading</div>
        {trend && !trend.why && <Trend m={m} trend={trend} period={block.period} />}
        <p className="aug-fs-sm" style={para}>
          {trend?.why ? `Its earlier ranges could not be read: ${trend.why}.`
            : u && m.equal_age && !m.equal_age.equal ? <>Its usual range is <b style={{ color: "var(--t1)", fontWeight: 500 }}>{bandWords(u.low, u.high, m.unit)}</b>, from the {u.n} ranges before. This figure is not held against it.</>
            : u ? <>{u.outside === "above" ? "Above" : u.outside === "below" ? "Below" : "Inside"} its usual range of{" "}
                <b style={{ color: "var(--t1)", fontWeight: 500 }}>{bandWords(u.low, u.high, m.unit)}</b>, from the {u.n} ranges before.</>
              : "Too few earlier readings to say what is usual."}
        </p>
        {trend?.same_age && <p className="aug-fs-sm" style={para}>Every range here is read at the same age, so these comparisons are fair.</p>}
        {m.equal_age && !m.equal_age.equal && <p className="aug-fs-sm" style={para}>{`Not at equal age: ${m.equal_age.why}.`}</p>}
      </div>
      <div>
        <div className="aug-fs-xs" style={label}>What the platform knows</div>
        {work.length === 0 ? (
          <p className="aug-fs-sm" style={para}>
            {briefed ? "The Briefing for this range says nothing of this metric." : "No Briefing has been written for this range, and it is where the platform's work on a metric is gathered."}
          </p>
        ) : work.map(w => (
          <div key={`${w.kind}:${w.text.slice(0, 40)}`} data-testid="ledger-work" style={{ marginBottom: 10 }}>
            <div className="aug-fs-xs" style={{ ...ROW, gap: 6, marginBottom: 4, ...MUTED }}>
              <Chip>{w.kind}</Chip>{w.when && <span>{w.when}</span>}
            </div>
            <p className="aug-fs-sm" style={{ ...para, color: "var(--t1)", marginBottom: 6 }}>{w.text}</p>
            {(w.run || w.decision) && (
              <Button size="xs" variant="ghost" onClick={() => openWork(w)}>{w.run ? "Open the deep analysis" : "Open the decision"}</Button>
            )}
          </div>
        ))}
      </div>
      <div>
        <div className="aug-fs-xs" style={label}>How it is measured</div>
        {meaning && <p className="aug-fs-sm" style={para}>{meaning}</p>}
        {trend && trend.tables?.length > 0 && <p className="aug-fs-xs" style={{ ...para, ...MUTED }}>{`Reads ${trend.tables.join(", ")}`}</p>}
        {item?.expected ? (
          <p className="aug-fs-xs" style={{ ...para, ...MUTED }}>
            {`Expected ${expected?.target ? targetWords(expected.target, block.period) : "next"}: ${expectedWords(item.expected, m.unit)}. `}
            {bandBasisWords(item.expected)}
          </p>
        ) : item?.why ? <p className="aug-fs-xs" style={{ ...para, ...MUTED }}>{`No band is stated: ${item.why}.`}</p> : null}
        <div style={{ ...ROW, gap: 6 }}>
          {openDetail && (
            <Button size="xs" variant="ghost" onClick={() => openDetail({ measure: m, block, expected: expected?.target ? { target: expected.target, item } : undefined })}>
              See how it is defined
            </Button>
          )}
          {askWhy && <Button size="xs" variant="ghost" onClick={() => askWhy(whyQuestion(m, block))}>Ask why it moved</Button>}
        </div>
      </div>
    </div>
  );
}

type Filter = "all" | "key" | "unmeasured";

export function MetricsLedger({ connectionId, schema, block: measuredBlock }: {
  connectionId: string; schema?: string; block: BriefingRangeBlock;
}) {
  const block = useMemo(() => ownFigures(measuredBlock), [measuredBlock]);
  const { trends, done } = useTrends(connectionId, schema, block);
  // Reading these books the period's expected-next bands as predictions, the first time it is read.
  const expected = useLoad(() => readExpectedNext(connectionId, rangeOf(block), schema), [connectionId, schema, block.key]);
  // A read: the Briefing last written for this range and this person's reader. It never writes one.
  const read = useLoad(() => readBriefingEdition(connectionId, briefingRangeOf(rangeOf(block)), undefined, schema), [connectionId, schema, block.key]);
  const edition = editionFor(read.data, block);
  const coverage = useLoad(() => getMetricCoverage(connectionId, schema), [connectionId, schema]);

  const [filter, setFilter] = useState<Filter>("all");
  const [term, setTerm] = useState("");
  const [open, setOpen] = useState("");
  useEffect(() => { setOpen(""); setFilter("all"); setTerm(""); }, [block.key]);

  const twins = useMemo(() => (done ? twinsOf(block.measured, trends) : {}), [done, block.measured, trends]);
  const moveOf = (m: BriefingRangeMeasure) => keyMove(m, trends[m.metric]);
  const toneOf = (m: BriefingRangeMeasure) => toneOfMove(moveOf(m), m.better);
  const zOf = (m: BriefingRangeMeasure) => Math.abs(trends[m.metric]?.usual?.z ?? 0);
  const areas = areasOf(block);
  // what is bad first, then what is furthest from its usual range
  const key = block.measured.filter(m => moveOf(m))
    .sort((a, b) => Number(toneOf(b) === "bad") - Number(toneOf(a) === "bad") || zOf(b) - zOf(a));
  const settling = block.measured.filter(m => m.status !== "final").length;
  const ended = block.unmeasured.filter(u => u.data_ends).length;
  const { current, previous } = figurePeriods(block);
  const hasYear = block.measured.some(m => m.last_year !== null);
  const target = expected.data?.target;
  const columns = 5 + (hasYear ? 1 : 0) + (target ? 1 : 0);
  const shown = new Set(areas.map(d => d.name));
  const untouched = (coverage.data?.areas ?? []).filter(a => a.has_data && a.metrics.length === 0 && !shown.has(a.name)).map(a => a.name);

  const q = term.trim().toLowerCase();
  const hit = (name: string) => name.toLowerCase().includes(q);
  const works = (m: BriefingRangeMeasure) => workFor(m, edition);

  const row = (m: BriefingRangeMeasure, withArea: boolean) => {
    const trend = trends[m.metric];
    const isOpen = open === m.metric;
    const move = moveOf(m);
    const tone = toneOf(m);
    const said = readoutOf(m, trend, block.period, twins[m.metric]);
    const band = expected.data?.items.find(i => i.metric === m.metric);
    const work = works(m);
    const cell = (against: "previous" | "last_year", words: string) => {
      const c = changeWords(m, against);
      const colour = c.dir === 0 ? "var(--t3)" : move && tone ? ((c.dir > 0) === (m.better === "up") ? TONE.good : TONE.bad) : "var(--t2)";
      return <span title={c.why ?? `${words}: ${figureWords(m[against], m.unit, against === "previous" ? m.previous_text : m.last_year_text)}`} style={{ color: colour }}>{c.text}</span>;
    };
    return (
      <Fragment key={m.metric}>
        <tr data-testid={`ledger-row-${m.metric}`} data-key={move ? "true" : undefined} style={isOpen ? { background: "var(--bg-3)" } : undefined}>
          <td style={CELL}>
            <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
              <Button variant="link" size="xs" aria-expanded={isOpen} title={m.name}
                onClick={() => setOpen(isOpen ? "" : m.metric)}
                style={{ padding: 0, height: "auto", color: "var(--t1)", fontWeight: 500, minWidth: 0, flex: "0 1 auto" }}>
                <span style={{ display: "inline-flex", flexShrink: 0 }}><Icon name={isOpen ? "chevd" : "chevr"} size={11} /></span>
                <span className="aug-fs-chrome" style={ONE_LINE}>{m.name}</span>
              </Button>
              <span style={{ display: "inline-flex", flexShrink: 0 }}>
                {m.equal_age && !m.equal_age.equal ? <Chip tone="amber" title={m.equal_age.why}>not at equal age</Chip>
                  : m.status !== "final" && <Chip title="Its newest days are still settling, so this figure can still move">{m.status === "to_date" ? "to date" : "still settling"}</Chip>}
              </span>
              {withArea && m.area && <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, flex: "1 1 0" }}>{m.area.name}</span>}
            </div>
          </td>
          <td style={NUMBER}><span className="aug-fs-ui" style={{ fontWeight: 600, color: "var(--t1)" }}>{figureWords(m.current, m.unit, m.current_text)}</span></td>
          <td style={CELL}><Spark trend={trend} tone={tone} /></td>
          <td style={NUMBER} className="aug-fs-sm">{cell("previous", previous)}</td>
          {hasYear && <td style={NUMBER} className="aug-fs-sm">{cell("last_year", "A year earlier")}</td>}
          {target && (
            <td style={{ ...CELL, ...NUM, whiteSpace: "nowrap" }} className="aug-fs-xs" title={band?.expected ? bandBasisWords(band.expected) : band?.why || undefined}>
              <span style={MUTED}>{band?.expected ? expectedWords(band.expected, m.unit) : "not predicted"}</span>
            </td>
          )}
          <td style={CELL} className="aug-fs-sm">
            <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0, color: said.plain ? "var(--t3)" : "var(--t1)" }}>
              {move && <Dot color={DOT[tone]} title={`A key movement: ${move} its usual range`} />}
              <span data-testid="ledger-readout" title={said.words} style={{ ...ONE_LINE, flex: "0 1 auto" }}>{said.words}</span>
              {work.filter(w => w.run || w.decision).map(w => (
                <Button key={`${w.kind}:${w.text.slice(0, 24)}`} size="xs" variant="ghost" onClick={() => setOpen(m.metric)}>{w.kind.toLowerCase()}</Button>
              ))}
              {bandDoubt(band?.expected) && <Chip title={bandBasisWords(band!.expected!)}>{bandDoubt(band?.expected)}</Chip>}
            </div>
          </td>
        </tr>
        {isOpen && (
          <tr data-testid="ledger-open" style={{ background: "var(--bg-3)" }}>
            <td colSpan={columns} style={{ ...CELL, padding: "4px 12px 14px 27px", borderBottom: "1px solid var(--b1)" }}>
              <Reasons m={m} trend={trend} work={work} meaning={meaningOf(m, edition)} expected={expected.data} block={block} briefed={!!edition?.built} />
            </td>
          </tr>
        )}
      </Fragment>
    );
  };

  const groupHead = (name: string, words: string) => (
    <tr><td colSpan={columns} className="aug-fs-xs" style={{ ...CELL, background: "var(--bg-1)", padding: "9px 12px 5px", ...MUTED }}>
      <span style={{ textTransform: "uppercase", letterSpacing: ".06em" }}>{name}</span>
      {words && <span style={{ marginLeft: 8, ...NUM }}>{words}</span>}
    </td></tr>
  );

  let found = 0;
  const bodies = filter === "key" ? (() => {
    const rows = key.filter(m => hit(m.name));
    found = rows.length;
    return rows.map(m => row(m, true));
  })() : areas.map(d => {
    const rows = filter === "unmeasured" ? [] : d.rows.filter(m => hit(m.name));
    const held = d.notMeasured.map(n => ({ ...n, names: n.names.filter(hit) })).filter(n => n.names.length);
    if (!rows.length && !held.length) return null;
    const heldCount = held.reduce((t, n) => t + n.names.length, 0);
    const keys = rows.filter(m => moveOf(m)).length;
    found += rows.length + heldCount;
    return (
      <Fragment key={d.id || d.name}>
        {groupHead(d.name, [rows.length ? formatCount(rows.length) : "", keys ? countNoun(keys, "key movement") : "",
          heldCount ? `${formatCount(heldCount)} not measured` : ""].filter(Boolean).join(" · "))}
        {rows.map(m => row(m, false))}
        {held.map(n => (
          <tr key={n.why} data-testid="ledger-not-measured" style={{ background: HATCH }}>
            <td colSpan={2} className="aug-fs-sm" style={{ ...CELL, paddingLeft: 27, color: "var(--t2)" }}>{n.names.join(", ")}</td>
            <td colSpan={columns - 2} className="aug-fs-sm" style={{ ...CELL, color: "var(--t2)" }}>
              <span style={{ ...ROW, gap: 8 }}>
                {n.why}
                {!n.ended && !n.deprecated && (
                  <Button size="xs" variant="ghost" onClick={() => requestTab("semantic", { conn: connectionId })}>Open in the Semantic Layer</Button>
                )}
              </span>
            </td>
          </tr>
        ))}
      </Fragment>
    );
  });
  const total = filter === "key" ? key.length : block.measured.length + block.unmeasured.length;

  const flat = () => ({
    columns: ["Area", "Metric", current, `vs ${previous}`, ...(hasYear ? ["vs a year earlier"] : []), "Expected next", "Readout", "Status"],
    rows: rawCells(block.measured.map(m => {
      const band = expected.data?.items.find(i => i.metric === m.metric)?.expected;
      return [m.area?.name ?? "", m.name, figureWords(m.current, m.unit, m.current_text), changeWords(m, "previous").text,
        ...(hasYear ? [changeWords(m, "last_year").text] : []), band ? expectedWords(band, m.unit) : "",
        readoutOf(m, trends[m.metric], block.period, twins[m.metric]).words, m.status];
    })),
  });

  return (
    <div data-testid="metrics-ledger" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div data-testid="ledger-tally" className="aug-fs-sm" style={{ color: "var(--t2)", ...NUM }}>
        {`${formatCount(block.measured.length)} measured`}
        {done && ` · ${countNoun(key.length, "key movement")}`}
        {settling > 0 && ` · ${formatCount(settling)} still settling`}
        {block.unmeasured.length > 0 && ` · ${formatCount(block.unmeasured.length)} not measured`}
      </div>

      <NeedsYou testId="dashboard-needs" empty="Nothing needs you — every approved metric is measured for this period">
        {block.unmeasured.length > 0 && (
          <NeedsRow testId="needs-unmeasured" title={`${countNoun(block.unmeasured.length, "approved metric")} ${block.unmeasured.length === 1 ? "is" : "are"} not measured for ${current}`}
            detail={[ended > 0 ? `${formatCount(ended)} ${ended === 1 ? "has" : "have"} no data this recent` : "",
              block.unmeasured.length > ended ? `${formatCount(block.unmeasured.length - ended)} for another reason` : ""].filter(Boolean).join(", ")}
            actions={<Button size="xs" variant="secondary" onClick={() => { setFilter("unmeasured"); setTerm(""); }}>See them</Button>} />
        )}
      </NeedsYou>

      <div style={{ ...ROW, gap: 10 }}>
        <Segmented label="Which metrics" value={filter === "unmeasured" ? "" : filter} onChange={v => setFilter(v as Filter)}
          options={[{ value: "all", label: `All ${formatCount(block.measured.length)}` },
            { value: "key", label: `Key movements${done ? ` ${formatCount(key.length)}` : ""}`, title: "Metrics outside their usual range, what needs watching first" }]} />
        <div style={{ width: 220 }}>
          <Input value={term} onChange={e => setTerm(e.target.value)} placeholder="Find a metric" aria-label="Find a metric" />
        </div>
        {q && <span data-testid="ledger-found" className="aug-fs-xs" style={MUTED}>{`${formatCount(found)} of ${formatCount(total)}`}</span>}
        {filter === "unmeasured" && (
          <span className="aug-fs-xs" style={{ ...ROW, gap: 8, ...MUTED }}>
            {`${formatCount(block.unmeasured.length)} not measured`}
            <Button size="xs" variant="ghost" onClick={() => setFilter("all")}>Show all</Button>
          </span>
        )}
        <span style={{ marginLeft: "auto" }}><TableActions name={`Metrics ${current}`} read={flat} /></span>
      </div>

      <div className="aug-ledger-frame" style={{ border: "1px solid var(--card-edge)", borderRadius: "var(--r3)", background: "var(--bg-2)" }}>
        <table className="aug-fs-sm" style={{ width: "100%", borderCollapse: "separate", borderSpacing: 0, tableLayout: "fixed" }}>
          <colgroup>
            <col style={{ width: "25%" }} /><col style={{ width: "9%" }} /><col style={{ width: 96 }} /><col style={{ width: "8%" }} />
            {hasYear && <col style={{ width: "8%" }} />}{target && <col style={{ width: "13%" }} />}<col />
          </colgroup>
          <thead><tr className="aug-fs-xs">
            <th style={HEAD}>Metric</th>
            <th style={{ ...HEAD, textAlign: "right" }}>{current}</th>
            <th style={HEAD}>Trend</th>
            <th style={{ ...HEAD, textAlign: "right" }}>{`vs ${previous}`}</th>
            {hasYear && <th style={{ ...HEAD, textAlign: "right" }}>vs a year ago</th>}
            {target && <th style={HEAD} title="A band each metric's own past puts on the next range, not a target">{`Expected ${targetWords(target, block.period)}`}</th>}
            <th style={HEAD}>Readout</th>
          </tr></thead>
          <tbody>
            {found === 0 ? (
              <tr><td colSpan={columns} data-testid="ledger-none" style={{ ...CELL, padding: 26, textAlign: "center", ...MUTED }}>
                {q ? `No ${filter === "key" ? "key movement" : "metric"} matches “${term.trim()}”.` : filter === "key" && !done ? "Reading each metric's past…" : filter === "key" ? "Nothing left its usual range." : "Nothing here."}
              </td></tr>
            ) : bodies}
            {filter === "all" && !q && untouched.length > 0 && (
              <tr><td colSpan={columns} data-testid="ledger-untouched" className="aug-fs-xs" style={{ ...CELL, borderBottom: 0, padding: "10px 12px", ...MUTED }}>
                {`The data also holds ${untouched.join(" and ")}, with no metric reading ${untouched.length === 1 ? "it" : "them"} yet.`}
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="aug-fs-xs" style={MUTED}>
        A key movement is a metric outside its usual range: the band in each trend. Colour marks only those. Select a metric to see how it is read.
      </div>
    </div>
  );
}
