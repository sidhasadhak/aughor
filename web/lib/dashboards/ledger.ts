/**
 * The Metrics dashboard as a ledger (`design-mockups/metric-ledger-lux.html`; the user, 2026-11-04: "Lets move our Metrics
 * Dashboards in this manner"): what each row says, which area it reads in, and which rows are key movements. Every word
 * is written here by rule from what was measured, so a readout cannot state what the figures do not. What the platform's
 * own work says of a metric comes word for word from the Briefing it was written for. Pure: nothing here fetches.
 */
import type {
  BriefingEdition, BriefingRange, BriefingRangeBlock, BriefingRangeMeasure, EditionBlock, EditionSource, ExpectedBand, ExpectedNext,
  MetricTrend, RangePreset,
} from "@/lib/api";
import { SYMBOL, measuredBeforeWords, parseCited, rangeWord } from "@/lib/briefingEdition";
import { endsWords, periodShort, sentence } from "@/lib/dashboards/figures";

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// ── a figure and its change, in the metric's own terms ───────────────────────────────────────────────────────────────

type Unit = { kind: "money"; symbol: string } | { kind: "share" | "percent" | "days" | "plain" };

/** What a metric's unit says of how to print it. A declared unit is often a sentence ("ratio 0-1 (e-commerce typically
 *  0.005-0.05)", "EUR, typically 300-2000 for luxury orders"), so only its first word is read. */
export function unitOf(unit: string | null | undefined): Unit {
  const first = (unit ?? "").trim().split(/[\s,(]/)[0];
  const symbol = SYMBOL[first.toUpperCase()];
  if (symbol) return { kind: "money", symbol };
  if (/^ratio$/i.test(first)) return { kind: "share" };
  if (/^(percent|%)$/i.test(first)) return { kind: "percent" };
  if (/^days?$/i.test(first)) return { kind: "days" };
  return { kind: "plain" };
}

const group = (v: number, places: number) =>
  v.toLocaleString("en-GB", { minimumFractionDigits: places, maximumFractionDigits: places });

/** A figure in a ledger's cell: exact, so a column of them can be compared; two places on a percentage under 10. */
export function figureWords(v: number | null | undefined, unit: string | null | undefined, fallback?: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return fallback ?? "—";
  const u = unitOf(unit);
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (u.kind === "money") return `${sign}${u.symbol}${group(a, a >= 100 ? 0 : 2)}`;
  if (u.kind === "share" || u.kind === "percent") {
    const p = u.kind === "share" ? a * 100 : a;
    return `${sign}${p.toFixed(p < 10 ? 2 : 1)}%`;
  }
  if (u.kind === "days") return `${sign}${a.toFixed(2)} days`;
  return fallback ?? `${sign}${group(a, Number.isInteger(a) ? 0 : 2)}`;
}

/** A low and a high in one cell, the unit said once where it would repeat. */
export function bandWords(low: number | null | undefined, high: number | null | undefined, unit: string | null | undefined): string {
  if (low === null || low === undefined || high === null || high === undefined) return "";
  const days = unitOf(unit).kind === "days";
  return `${figureWords(low, unit).replace(" days", days ? "" : " days")} – ${figureWords(high, unit)}`;
}

/** What a metric is expected to read next: in its unit where this page can print it, else as the server said it. */
export function expectedWords(band: { low: number | null; high: number | null; text: string }, unit: string | null | undefined): string {
  return unitOf(unit).kind === "plain" ? band.text : bandWords(band.low, band.high, unit) || band.text;
}

/** The range a band is for, in the words of the ledger's own columns. */
export function targetWords(target: NonNullable<ExpectedNext["target"]>, period: string): string {
  const end = new Date(Date.parse(`${target.last_day}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
  return periodShort(target.start, end, period);
}

/** What a band stands on and how it has done: what it was built from (the server's words, up to where they state the band
 *  itself), what it says of itself, and how often it has been right. A band is not a promise, so this is always said. */
export function bandBasisWords(band: ExpectedBand): string {
  const from = (band.must_say[0] ?? "").split(":")[0].trim();
  const stated = band.coverage ? `, stated to hold ${Math.round(band.coverage * 100)}% of the time` : "";
  const held = band.cases ? `On this metric it has held ${band.held} of ${band.cases} times.` : "It has too few ranges to test it on.";
  return `A band from its own past, not a target${stated}. ${from ? `From ${from}. ` : ""}${held}`;
}

/** "held 1 of 4": said on the row itself where a band has been wrong more often than right, or its range would read as
 *  more than it is. Elsewhere it waits in the row's reasons. */
export function bandDoubt(band: ExpectedBand | null | undefined): string {
  return band && band.cases > 0 && band.held * 2 < band.cases ? `held ${band.held} of ${band.cases}` : "";
}

export interface Change { text: string; dir: -1 | 0 | 1; why?: string }

/** The change against a comparison: points for a share, days for days, a percentage of where it was otherwise. Nothing is
 *  stated where either side covers only part of its range or the comparison is withheld, and that is said. */
export function changeWords(m: BriefingRangeMeasure, against: "previous" | "last_year"): Change {
  const other = m[against];
  if (m.current_partial) return { text: "—", dir: 0, why: `It covers only ${m.current_partial}, so no change is stated` };
  if (against === "previous" && m.previous_partial) {
    return { text: "—", dir: 0, why: `Its comparison covers only ${m.previous_partial}, so no change is stated` };
  }
  if (m.current === null || other === null) return { text: "—", dir: 0, why: "There is nothing to compare it with" };
  const u = unitOf(m.unit);
  const arrow = (d: number) => (d > 0 ? "▲" : "▼");
  const dirOf = (d: number) => (d > 0 ? 1 : -1) as 1 | -1;
  if (u.kind === "share" || u.kind === "percent") {
    const pts = (m.current - other) * (u.kind === "share" ? 100 : 1);
    const places = Math.abs(u.kind === "share" ? m.current * 100 : m.current) < 10 ? 2 : 1;
    return Number(Math.abs(pts).toFixed(places)) === 0 ? { text: "flat", dir: 0 }
      : { text: `${arrow(pts)} ${Math.abs(pts).toFixed(places)} pts`, dir: dirOf(pts) };
  }
  if (u.kind === "days") {
    const d = m.current - other;
    return Number(Math.abs(d).toFixed(2)) === 0 ? { text: "flat", dir: 0 } : { text: `${arrow(d)} ${Math.abs(d).toFixed(2)} days`, dir: dirOf(d) };
  }
  const rel = (against === "previous" ? m.rel : m.rel_last_year) ?? (other === 0 ? null : (m.current - other) / Math.abs(other));
  if (rel === null) return { text: "—", dir: 0, why: "Its comparison is zero, so no percentage is stated" };
  const r = rel * 100;
  if (Math.abs(r) < 0.05) return { text: "flat", dir: 0 };
  return { text: `${arrow(r)} ${Math.abs(r).toFixed(Math.abs(r) < 10 ? 1 : 0)}%`, dir: dirOf(r) };
}

// ── what a row says ──────────────────────────────────────────────────────────────────────────────────────────────────

/** A figure the server says cannot be held against its past: part of any difference would be its age, not a move. On
 *  theLook, whose recent rows are still being written, reading these as movements flagged every metric it has. */
const unequal = (m: BriefingRangeMeasure) => !!m.equal_age && !m.equal_age.equal;

/** Whether a row is a key movement, and which way: outside its usual range. A range still under way is not, because
 *  part of a month reads low against whole ones, and neither is a figure covering part of its range or one not at equal
 *  age with what it would be measured against. */
export function keyMove(m: BriefingRangeMeasure, trend: MetricTrend | undefined): "above" | "below" | "" {
  if (m.status === "to_date" || m.current_partial || unequal(m)) return "";
  return trend?.usual?.outside ?? "";
}

/** Good, bad or neither for a row that moved. Colour marks only key movements, and only where someone has said which way
 *  is good: anywhere else it would be a judgement the data does not hold. */
export function toneOfMove(move: "above" | "below" | "", better: string | null | undefined): "good" | "bad" | "" {
  if (!move || (better !== "up" && better !== "down")) return "";
  return (move === "above") === (better === "up") ? "good" : "bad";
}

/** A range by when it began: "Oct", or "Oct ’25" where its year is not the one named or none is. */
export function shortOf(iso: string, period: string, sameYearAs?: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (period === "year") return String(d.getUTCFullYear());
  const year = sameYearAs && d.getUTCFullYear() === new Date(`${sameYearAs.slice(0, 10)}T00:00:00Z`).getUTCFullYear()
    ? "" : ` ’${String(d.getUTCFullYear()).slice(2)}`;
  return period === "month" ? `${MONTH[d.getUTCMonth()]}${year}` : `${d.getUTCDate()} ${MONTH[d.getUTCMonth()]}${year}`;
}

/** "highest in 13 months", or "lowest since May": where the figure stands among its own past, when that is worth saying.
 *  A rank among only the usual range's few is not said in a range's own words. */
export function rankWords(trend: MetricTrend | undefined, period: string): string {
  const read = (trend?.series ?? []).filter(p => typeof p.value === "number") as { start: string; value: number }[];
  if (read.length < 3 || !trend?.usual) return "";
  const cur = read[read.length - 1];
  const before = read.slice(0, -1);
  const word = rangeWord(period, read.length);
  if (cur.value >= Math.max(...before.map(p => p.value))) return `highest in ${read.length} ${word}`;
  if (cur.value <= Math.min(...before.map(p => p.value))) return `lowest in ${read.length} ${word}`;
  const near = before.slice(-trend.usual.n);
  const since = (hit: (v: number) => boolean) => {
    const last = [...before].reverse().find(p => hit(p.value));
    return last ? shortOf(last.start, period, cur.start) : "";
  };
  if (cur.value >= Math.max(...near.map(p => p.value))) return `highest since ${since(v => v >= cur.value)}`;
  if (cur.value <= Math.min(...near.map(p => p.value))) return `lowest since ${since(v => v <= cur.value)}`;
  return "";
}

/** The metric an identical metric was already listed as: two names for one figure, read the same in every range shown. */
export function twinsOf(measured: BriefingRangeMeasure[], trends: Record<string, MetricTrend | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  const values = (t: MetricTrend | undefined) => (t?.series ?? []).map(p => p.value);
  const same = (a: (number | null)[], b: (number | null)[]) => a.length >= 3 && a.length === b.length
    && a.every((v, i) => v !== null && b[i] !== null && Math.abs(v - (b[i] as number)) <= 1e-6 * Math.max(1, Math.abs(v)));
  measured.forEach((m, i) => {
    // one unit: a share and a sum that happen to move alike are not one figure
    const earlier = measured.slice(0, i).find(o => unitOf(o.unit).kind === unitOf(m.unit).kind
      && same(values(trends[m.metric]), values(trends[o.metric])));
    if (earlier) out[m.metric] = earlier.name;
  });
  return out;
}

export interface Readout { words: string; plain: boolean }

/** A row's readout, written by rule from what was measured. A row in its usual range with nothing else to say reads
 *  quietly; there is no sentence to pad it with. */
export function readoutOf(m: BriefingRangeMeasure, trend: MetricTrend | undefined, period: string, twin?: string): Readout {
  if (twin) return { words: `Reads the same as ${twin}`, plain: false };
  if (m.status === "to_date") return { words: "Under way, so not read against its usual range", plain: true };
  if (m.current_partial) return { words: `Covers only ${m.current_partial}`, plain: true };
  if (unequal(m)) return { words: "Not read against its usual range", plain: true };
  if (!trend) return { words: "", plain: true };
  if (trend.why) return { words: "Its earlier ranges could not be read", plain: true };
  if (!trend.usual) return { words: "Too few earlier readings to say what is usual", plain: true };
  const atAge = trend.same_age ? " at this age" : "";
  const rank = rankWords(trend, period);
  if (trend.usual.outside) {
    const side = trend.usual.outside === "above" ? "Above" : "Below";
    return { words: `${side} usual${atAge}${rank ? `, ${rank}` : ""}`, plain: false };
  }
  const base = `In usual range${atAge}`;
  if (rank) return { words: `${base}, ${rank}`, plain: false };
  const ly = m.rel_last_year;
  const u = unitOf(m.unit).kind;
  const far = (u === "share" || u === "percent")
    ? m.last_year !== null && m.current !== null && Math.abs(m.current - m.last_year) * (u === "share" ? 100 : 1) >= 2
    : ly !== null && u !== "days" && Math.abs(ly) >= 0.1;
  if (far && m.last_year !== null && m.current !== null) {
    return { words: `${base}, ${m.current > m.last_year ? "above" : "below"} a year ago`, plain: false };
  }
  return { words: base, plain: true };
}

// ── an area's rows ──────────────────────────────────────────────────────────────────────────────────────────────────

export interface NotMeasured { names: string[]; why: string; ended: boolean; deprecated: boolean }

export interface AreaRows {
  id: string;
  name: string;
  order: number;
  rows: BriefingRangeMeasure[];
  notMeasured: NotMeasured[];
}

const ELSE = { id: "", name: "Everything else", order: 10 ** 7 };

/** Why a metric is not measured, in the few words its row can hold; the ones that share a reason read as one row. */
function whyNot(u: BriefingRangeBlock["unmeasured"][number]): NotMeasured {
  const deprecated = /deprecated/i.test(u.reason);
  return { names: [u.name], ended: !!u.data_ends, deprecated,
           why: u.data_ends ? `Data ended ${endsWords([u.data_ends])}` : sentence(u.reason) };
}

/** Every metric in its area — the industry's areas, in the order its business reads them — what was not measured among
 *  the rest. A row keeps its place whatever it reads, so a person learns where a metric is: what moved is ranked under Key
 *  movements, and a trend read last (a large table's, 26 seconds on LuxExperience) never moves a row under the pointer. */
export function areasOf(block: BriefingRangeBlock): AreaRows[] {
  const all = new Map<string, AreaRows>();
  const of = (area: { id: string; name: string; order?: number } | null | undefined) => {
    const a = area ?? ELSE;
    const known = all.get(a.id);
    if (known) return known;
    const made: AreaRows = { id: a.id, name: a.name, order: a.order ?? ELSE.order, rows: [], notMeasured: [] };
    all.set(a.id, made);
    return made;
  };
  block.measured.forEach(m => of(m.area).rows.push(m));
  block.unmeasured.forEach(u => {
    const d = of(u.area);
    const said = whyNot(u);
    const same = d.notMeasured.find(n => n.why === said.why);
    if (same) same.names.push(u.name); else d.notMeasured.push(said);
  });
  return [...all.values()].sort((a, b) => a.order - b.order);
}

// ── what the platform already knows of a metric ──────────────────────────────────────────────────────────────────────

export interface Work {
  kind: string;
  when: string;
  text: string;
  /** What the platform says of it, whatever the words around it say. */
  note?: string;
  /** How to open it. */
  run?: string;
  decision?: string;
}

const plain = (text: string | undefined) => parseCited(text).map(r => r.text).join("").trim();

/** The ways a metric is named in prose: its name without its parenthesis, that without its first word when three or more
 *  remain ("profit per order"), and an acronym it carries ("AOV"). */
export function namesOfMetric(name: string): string[] {
  const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const inner = /\(([A-Za-z]{2,6})\)/.exec(name)?.[1];
  const base = norm(name.replace(/\([^)]*\)/g, " "));
  const words = base.split(" ");
  return [base, words.length >= 4 ? words.slice(1).join(" ") : "", inner ? norm(inner) : ""].filter(Boolean);
}

const says = (text: string, name: string) => {
  const hay = ` ${text.toLowerCase().replace(/[^a-z0-9]+/g, " ")} `;
  return namesOfMetric(name).some(n => hay.includes(` ${n} `));
};

const facts = (s: EditionSource, k: string) => (typeof s.facts?.[k] === "string" ? (s.facts[k] as string) : "");

function workOf(block: EditionBlock, src: EditionSource): Work | null {
  const text = plain(block.text);
  if (!text) return null;
  if (src.kind === "analysis") {
    const confidence = facts(src, "confidence").toLowerCase();
    return { kind: "Deep analysis", when: [facts(src, "completed"), confidence && `${confidence} confidence`].filter(Boolean).join(" · "),
             text, run: facts(src, "inv_id") || undefined, ...(measuredBeforeWords(src) ? { note: measuredBeforeWords(src) } : {}) };
  }
  if (src.kind === "decision") return { kind: "Decision", when: facts(src, "state"), text, decision: facts(src, "decision_id") || undefined };
  if (src.kind === "finding") return { kind: "Explorer finding", when: facts(src, "area"), text };
  if (src.kind === "discussion") return { kind: "Said", when: [facts(src, "who"), facts(src, "when")].filter(Boolean).join(" · "), text };
  return null;
}

const BRIEFING_PRESET: Partial<Record<RangePreset, RangePreset>> = {
  previous_week: "last_week", previous_month: "last_month", previous_year: "last_year",
};

/** The Briefing's name for a range. A dashboard says "previous month" where the Briefing keeps its edition under "last
 *  month": the same month, and read under the wrong name it reads as no Briefing at all. */
export function briefingRangeOf(range: BriefingRange): BriefingRange {
  const preset = BRIEFING_PRESET[range.preset];
  return preset ? { preset } : range;
}

/** The edition, only if it is of this very range. "Last month" is the last one whose numbers have settled, so it can name
 *  a different month from "previous month", and what it wrote then is not what this range read. */
export function editionFor(edition: BriefingEdition | null | undefined, block: BriefingRangeBlock): BriefingEdition | null {
  const period = edition?.period;
  return edition && period && period.start === block.start && period.last_day === block.last_day ? edition : null;
}

/** What the Briefing for this range and reader wrote of a metric: the line under its own figure, and the platform's work
 *  it read that names the metric. Word for word: nothing here writes, and a range with no Briefing has nothing to give. */
export function workFor(m: BriefingRangeMeasure, edition: BriefingEdition | null | undefined): Work[] {
  if (!edition?.built) return [];
  const sources = edition.sources ?? {};
  const figure = new Set((edition.period.measured ?? []).filter(f => f.metric === m.metric).map(f => f.id));
  const out: Work[] = [];
  for (const b of edition.blocks ?? []) {
    const src = b.source ? sources[b.source] : undefined;
    if (b.source && figure.has(b.source) && b.text) {
      out.push({ kind: "The Briefing", when: "", text: plain(b.text) });
    } else if (src && b.type === "context" && says(plain(b.text), m.name)) {
      const w = workOf(b, src);
      if (w) out.push(w);
    }
  }
  return out;
}

/** What the guide says a metric is for, where this range's Briefing carries it. */
export function meaningOf(m: BriefingRangeMeasure, edition: BriefingEdition | null | undefined): string {
  if (!edition?.built) return "";
  return (edition.period.measured ?? []).find(f => f.metric === m.metric)?.why ?? "";
}
