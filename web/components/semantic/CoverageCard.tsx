/**
 * Arc MC — how far a connection's metrics cover its business (ROADMAP §3.62; the user, 2026-10-26, on LuxExperience:
 * "only 12 proposed metrics.. not even 50% of the matrix"). The areas a business like this one is read by, in the map's
 * order — the income statement's first — each with the data placed in it, the metrics that read on it, what the
 * knowledge base would measure there, and the proposals waiting, every placement with its reason. An area is covered
 * only by an approved metric whose figures move; one that reads one value every month is said, and covers nothing.
 *
 * Opened on the figures read within the hour, then — when an approved metric's figures were not read yet — read again
 * with them, so no area reads covered before its figures are known. Adopting is per area, through the door that exists.
 */
import { useEffect, useState, type CSSProperties } from "react";

import { Card, Chip, Empty, MUTED, NUM, ONE_LINE, ROW, RULE, type Tone } from "@/components/clarity/kit";
import { AdoptProposals } from "@/components/semantic/AdoptProposals";
import { rowButtonStyle } from "@/components/semantic/parts";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import {
  getMetricCoverage, runMetricCoverage, writeMetricCoverage,
  type CatalogueMetric, type CoverageArea, type CoverageGate, type CoverageProposal, type MetricCoverage,
} from "@/lib/api";
import { countNoun, formatCount } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { ORIGIN_WORDS, dayWords } from "@/lib/semanticMetrics";

const STATE: Record<CoverageArea["state"], { tone: Tone; text: string; title: string }> = {
  covered: { tone: "up", text: "covered", title: "An approved metric reads on this area, and its figures move." },
  unchecked: { tone: "plain", text: "not checked", title: "Its approved metrics' figures have not been read yet." },
  uncovered: { tone: "amber", text: "no working metric", title: "It has data, and no approved metric that moves reads on it." },
  no_data: { tone: "plain", text: "no data", title: "No table placed in this area holds rows." },
};

const GRID: CSSProperties = {
  display: "grid", gridTemplateColumns: "minmax(200px, 2fr) minmax(130px, 1fr) minmax(120px, 1fr) minmax(130px, 1fr) 20px",
  columnGap: 14,
};

const GATE_WORDS: Record<string, string> = {
  runs: "runs", dated: "has a date", window: "a window bounds it", area: "reads its area", pattern: "computes its pattern",
  count: "counts as the ontology does", binding: "roles bound right", moves: "moves", sane_range: "in its sane range",
  twin: "not a twin",
};

/** The proposals of one area: what passed every check, then what a check refused, with why. */
export function proposalsOf(coverage: MetricCoverage, area: string): CoverageProposal[] {
  const mine = coverage.proposals.filter(p => p.area === area && !p.declined);
  return [...mine.filter(p => p.state === "proposed"), ...mine.filter(p => p.state !== "proposed")];
}

/** The verdicts a proposal's gates read, as one line: the failed one first. */
export function gateLine(gates: Record<string, CoverageGate>): string {
  const entries = Object.entries(gates || {});
  const failed = entries.filter(([, v]) => v.ok === false).map(([g, v]) => `${GATE_WORDS[g] ?? g}: no — ${v.why}`);
  if (failed.length) return failed.join(" · ");
  const passed = entries.filter(([, v]) => v.ok === true).map(([g]) => GATE_WORDS[g] ?? g);
  const unread = entries.filter(([, v]) => v.ok === null).map(([g]) => GATE_WORDS[g] ?? g);
  return [passed.length ? `✓ ${passed.join(" · ")}` : "", unread.length ? `not read: ${unread.join(", ")}` : ""]
    .filter(Boolean).join(" — ");
}

export function CoverageCard({ connId, schema, rows, onAdopted }: {
  connId: string;
  schema?: string;
  /** The catalogue's rows — what each area's adopt door adopts. */
  rows: CatalogueMetric[];
  onAdopted: () => void;
}) {
  const [coverage, setCoverage] = useState<MetricCoverage | null | undefined>(undefined);
  const [error, setError] = useState("");
  const [reading, setReading] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "run" | "write">("");
  const [note, setNote] = useState("");

  async function load(figures = false) {
    try {
      const got = await getMetricCoverage(connId, schema, figures);
      setCoverage(got);
      setError("");
      if (!figures && got && got.areas.some(a => a.state === "unchecked")) {
        setReading(true);
        try { setCoverage(await getMetricCoverage(connId, schema, true)); } finally { setReading(false); }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  useEffect(() => { setCoverage(undefined); void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [connId, schema]);

  if (coverage === null) return null;                                     // the coverage view is off
  if (coverage === undefined) {
    return error
      ? <Card label="Coverage" testId="metric-coverage"><Empty>The coverage could not be read: {error}</Empty></Card>
      : null;
  }

  const c = coverage.counts;
  const canRun = coverage.flags["metrics.coverage_proposals"] || coverage.flags["metrics.blind_spot_proposals"];
  const canWrite = coverage.flags["metrics.coverage_writer"];
  const spend = coverage.run?.spend;
  const toWrite = c.writable ?? coverage.areas.filter(a => a.writable).length;

  async function run() {
    setBusy("run"); setNote("");
    try {
      const out = await runMetricCoverage(connId, schema);
      setNote(out.started ? "Proposing — each proposal's figures are read before it is listed. Read this again in a few minutes."
        : "Nothing started: no proposer is on.");
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }
  async function write() {
    setBusy("write"); setNote("");
    try {
      const out = await writeMetricCoverage(connId, schema);
      setNote(out.started ? `Writing — ${countNoun(toWrite, "model call")}, one per area with patterns its metrics do not compute yet. Read this again in a few minutes.`
        : "The writer did not start.");
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); } finally { setBusy(""); }
  }

  return (
    <Card label="Coverage" testId="metric-coverage" right={<span style={{ ...ROW, gap: 6 }}>
      <span className="aug-fs-sm" style={{ ...MUTED, ...NUM }}>
        {`${formatCount(c.covered)} of ${formatCount(c.with_data)} areas with data covered`}
      </span>
      {canRun && <Button size="xs" variant="ghost" disabled={!!busy} onClick={() => void run()} title="Proposes by code — no model call">
        {busy === "run" ? "Proposing…" : "Propose by code"}
      </Button>}
      {canWrite && toWrite > 0 && <Button size="xs" variant="ghost" disabled={!!busy} onClick={() => void write()}
        title={`One model call for each of the ${toWrite} areas whose data has patterns no metric computes yet`}>
        {busy === "write" ? "Starting…" : `Write from the knowledge base · ${countNoun(toWrite, "call")}`}
      </Button>}
    </span>}>
      <p className="aug-fs-sm" style={{ ...MUTED, margin: "0 0 10px" }}>
        The areas a business like this one is read by, in the order it reads them. An area is covered by an approved
        metric whose figures move{c.open_patterns ? `; ${countNoun(c.open_patterns, "pattern")} of the knowledge base no metric computes yet` : ""}.
        {reading ? " Reading the approved metrics' figures…" : ""}
      </p>
      <div style={{ overflowX: "auto" }}>
        <div style={{ minWidth: 640 }}>
          <div className="aug-fs-xs" style={{ ...GRID, ...MUTED, textTransform: "uppercase", letterSpacing: ".06em", padding: "0 6px 6px" }}>
            <span>Area</span><span>Data</span><span>Metrics</span><span>Proposals</span><span />
          </div>
          {coverage.areas.map(a => {
            const isOpen = open === a.id;
            const working = a.metrics.filter(m => m.status === "approved" && m.moves?.ok === true).length;
            const state = STATE[a.state];
            return (
              <div key={a.id} data-testid="coverage-area" data-area={a.id}>
                <Button variant="ghost" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : a.id)} style={rowButtonStyle(isOpen, GRID)}>
                  <span style={{ minWidth: 0 }}>
                    <span className="aug-fs-chrome" style={{ ...ONE_LINE, display: "block", color: "var(--t1)", fontWeight: 500 }}>{a.name}</span>
                    <span className="aug-fs-xs" style={{ ...MUTED, ...ONE_LINE, display: "block" }}>{a.question}</span>
                  </span>
                  <span className="aug-fs-sm" style={{ ...NUM, color: a.has_data ? "var(--t2)" : "var(--t3)" }}>
                    {a.has_data ? `${formatCount(a.rows)} rows · ${countNoun(a.tables.length, "table")}` : "—"}
                  </span>
                  <span style={{ ...ROW, gap: 6 }}>
                    <Chip tone={state.tone} title={state.title} testId="coverage-state">{state.text}</Chip>
                    {a.metrics.length > 0 && <span className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>{`${working}/${a.metrics.length}`}</span>}
                  </span>
                  <span className="aug-fs-sm" style={{ ...NUM, color: a.adoptable ? "var(--t1)" : "var(--t3)" }}
                    title={a.open_patterns?.length ? `${countNoun(a.open_patterns.length, "pattern")} no metric here computes yet` : undefined}>
                    {a.proposals ? `${formatCount(a.adoptable)} ready${a.failed ? ` · ${formatCount(a.failed)} failed` : ""}`
                      : a.open_patterns?.length && a.has_data ? `${countNoun(a.open_patterns.length, "open pattern")}` : "—"}
                  </span>
                  <span style={{ display: "inline-flex", color: "var(--t3)" }}><Icon name={isOpen ? "chevd" : "chevr"} size={12} /></span>
                </Button>
                {isOpen && <AreaDetail coverage={coverage} area={a} connId={connId} schema={schema} rows={rows}
                  onAdopted={() => { onAdopted(); void load(); }} />}
              </div>
            );
          })}
        </div>
      </div>
      {coverage.unplaced_tables.length > 0 && (
        <p className="aug-fs-xs" style={{ ...MUTED, margin: "10px 0 0" }} data-testid="coverage-unplaced"
          title="Reference tables a metric does not read and no area's words name">
          {`Placed in no area: ${coverage.unplaced_tables.join(", ")}.`}
        </p>
      )}
      {spend && (
        <p className="aug-fs-xs" style={{ ...MUTED, margin: "6px 0 0" }} data-testid="coverage-spend">
          {`Written from the knowledge base by ${spend.model || "a model"}: ${countNoun(spend.calls, "model call")}, one per area, ${dayWords(spend.at)}`}
          {coverage.run?.why ? ` — ${coverage.run.why}` : ""}.
          {spend.areas.some(x => x.error) ? ` ${countNoun(spend.areas.filter(x => x.error).length, "call")} failed.` : ""}
        </p>
      )}
      {[...coverage.said, ...(coverage.run?.said ?? [])].length > 0 && (
        <p className="aug-fs-xs" style={{ color: "var(--amb4)", margin: "6px 0 0" }}>{[...coverage.said, ...(coverage.run?.said ?? [])].join(" · ")}</p>
      )}
      {note && <p className="aug-fs-sm" style={{ margin: "8px 0 0", color: "var(--t2)" }} data-testid="coverage-note">{note}</p>}
    </Card>
  );
}

function AreaDetail({ coverage, area, connId, schema, rows, onAdopted }: {
  coverage: MetricCoverage; area: CoverageArea; connId: string; schema?: string; rows: CatalogueMetric[]; onAdopted: () => void;
}) {
  const proposals = proposalsOf(coverage, area.id);
  const adoptRows = rows.filter(r => r.source !== "defined" && r.area === area.id);
  const spent = coverage.run?.spend?.areas.find(x => x.area === area.id);
  return (
    <div style={{ padding: "12px 6px 18px 14px", borderLeft: "2px solid var(--blue3)", display: "flex", flexDirection: "column", gap: 12 }}
      data-testid="coverage-detail">
      {withUniqueKeys(area.said, s => `said:${s}`).map(([key, s]) => (
        <p key={key} className="aug-fs-sm" style={{ margin: 0, color: "var(--amb4)" }}>{s}</p>
      ))}
      <section>
        <div className="aug-fs-xs" style={{ ...MUTED, textTransform: "uppercase", letterSpacing: ".06em" }}>Data</div>
        {area.tables.length === 0 ? <Empty>No table is placed here.</Empty> : withUniqueKeys(area.tables, t => `table:${t.name}`).map(([key, t]) => (
          <div key={key} className="aug-fs-sm" style={{ ...ROW, ...RULE, padding: "4px 0" }}>
            <span style={{ fontFamily: "var(--font-mono)", color: "var(--t1)" }}>{t.name}</span>
            <span style={{ ...MUTED, ...NUM }}>{t.rows != null ? `${formatCount(t.rows)} rows` : "rows not read"}</span>
            <span style={MUTED}>{t.why}</span>
          </div>
        ))}
      </section>
      <section>
        <div className="aug-fs-xs" style={{ ...MUTED, textTransform: "uppercase", letterSpacing: ".06em" }}>Metrics</div>
        {area.metrics.length === 0 ? <Empty>No metric reads on this area.</Empty> : withUniqueKeys(area.metrics, m => `metric:${m.name}`).map(([key, m]) => (
          <div key={key} className="aug-fs-sm" style={{ ...ROW, ...RULE, padding: "4px 0" }}>
            <span style={{ color: "var(--t1)" }}>{m.label}</span>
            <Chip>{m.status}</Chip>
            {m.moves?.ok === false && <Chip tone="amber" title={m.moves.why}>never moves</Chip>}
            <span style={MUTED}>{m.why}</span>
          </div>
        ))}
      </section>
      <section>
        <div className="aug-fs-xs" style={{ ...MUTED, textTransform: "uppercase", letterSpacing: ".06em" }}>
          {`The knowledge base · ${countNoun(area.patterns.length, "pattern")}`}
        </div>
        {area.patterns.length === 0 ? <Empty>No pattern covers this area yet.</Empty> : (
          <p className="aug-fs-sm" style={{ margin: "4px 0 0", color: "var(--t2)" }}>{area.patterns.map(p => p.title).join(" · ")}</p>
        )}
        {spent && spent.skipped.length > 0 && (
          <p className="aug-fs-xs" style={{ ...MUTED, margin: "4px 0 0" }}>
            {`Not written for this data: ${spent.skipped.map(s => `${s.pattern} (${s.why})`).join("; ")}.`}
          </p>
        )}
      </section>
      <section>
        <div className="aug-fs-xs" style={{ ...MUTED, textTransform: "uppercase", letterSpacing: ".06em" }}>
          {`Proposals · ${countNoun(proposals.length, "proposal")}`}
        </div>
        {proposals.length === 0 ? <Empty>Nothing is proposed for this area.</Empty>
          : withUniqueKeys(proposals, p => `proposal:${p.name}`).map(([key, p]) => (
            <div key={key} className="aug-fs-sm" style={{ ...RULE, padding: "6px 0" }} data-testid="coverage-proposal">
              <div style={{ ...ROW, gap: 6 }}>
                <span style={{ color: "var(--t1)", fontWeight: 500 }}>{p.label}</span>
                <Chip tone="violet">{ORIGIN_WORDS[p.source] ?? p.source}</Chip>
                <Chip tone={p.state === "proposed" ? "up" : "amber"}>{p.state === "proposed" ? "passed every check" : "failed a check"}</Chip>
                {p.pattern_title && <span style={MUTED}>{p.pattern_title}</span>}
              </div>
              <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 2 }}>{gateLine(p.gates)}</div>
            </div>
          ))}
      </section>
      {adoptRows.some(r => r.state === "proposed") && (
        <AdoptProposals connId={connId} schema={schema} rows={adoptRows} onDone={onAdopted} label={`Adopt ${area.name}'s proposals`} />
      )}
    </div>
  );
}
