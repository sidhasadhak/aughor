"use client";

/**
 * ProfileLayer.tsx — Intelligence › Profile: what Aughor knows about this business, beside the domains its findings
 * are filed under. Redone to `aughor-v2/CLARITY.md` (2026-10-13).
 *
 * A column on the left lists the domains as CLARITY's filter column — name · count · a 6px bar — under "Overview", which
 * is the profile itself (ProfilePanel), read like a page. A domain opens its own page beside the column: one line of
 * what it holds, then its findings grouped by novelty (said once per group, not as a tag on every row), the patterns
 * that involve it, and what it promoted to the org. A finding opens in place with the Briefing's finding actions.
 *
 * The Hub's domain rail came back on 2026-09-14 (the user's ask) and stays: it is the one place findings are read by
 * domain. A read that fails says so with Retry — the domains, the patterns and the org promotions each — never as an
 * empty list.
 */
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";

import { CARD, Chip, Empty, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { EvidenceDrawer, FindingActions } from "@/components/BriefingPanel";
import { ProfilePanel } from "@/components/ProfilePanel";
import { GroupHead } from "@/components/semantic/parts";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/ui/icon";
import { Input } from "@/components/ui/input";
import { Pending, SkeletonRows } from "@/components/ui/motion";
import { Segmented } from "@/components/ui/segmented";
import { ReadFailed } from "@/components/ui/states";
import { TabStrip } from "@/components/ui/tab-strip";
import { toast } from "@/components/ui/toast";
import {
  dedupeDomainInsights,
  getActionTriggers,
  getCanvasDomainInsights,
  getCanvasPatterns,
  getDomainInsights,
  getOrgIntelligence,
  getPatterns,
  insightUid,
  type ActionTrigger,
  type DomainInsights,
  type OrgInsight,
  type Pattern,
  type RecordedFinding,
} from "@/lib/api";
import { countNoun, formatCount, relTime } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";

// ── How the Hub read a domain ─────────────────────────────────────────────────────

/** A domain's findings and the explorer's budget for it, and a finding promoted to the org — the wire's names, said
 *  once here so the reader's word ("finding") is the one this file speaks. */
type Domain = DomainInsights;
type Promoted = OrgInsight;
const findingsOf = (d: Domain): RecordedFinding[] => d.insights;

/** Novelty in the Hub's three bands: 5 and up is high, 3–4 mid, the rest low. */
const BANDS = [
  { id: "high", name: "High novelty", title: "Novelty 5 and up", test: (n: number) => n >= 5 },
  { id: "mid", name: "Mid novelty", title: "Novelty 3 or 4", test: (n: number) => n >= 3 && n < 5 },
  { id: "low", name: "Low novelty", title: "Novelty below 3", test: (n: number) => n < 3 },
] as const;
const bandWord = (n: number) => (n >= 5 ? "high" : n >= 3 ? "mid" : "low");

/** The share of the explorer's query budget this domain has spent — what the Hub called "explored". */
function coveragePct(d: Domain): number {
  if (!d.budget_cap) return 0;
  return Math.min(100, Math.round((d.queries_used / d.budget_cap) * 100));
}

/** Top findings first: novelty, then confidence. */
const byRank = (a: RecordedFinding, b: RecordedFinding) =>
  (b.novelty - a.novelty) || ((b.confidence ?? 0) - (a.confidence ?? 0));

const sameDomain = (a: string | undefined, b: string) => (a ?? "").toLowerCase() === b.toLowerCase();

/** A row that opens in place: the summary is the button and what it opens sits below it, so a finding's own actions are
 *  never buttons nested inside a button. */
const ROW_BUTTON: CSSProperties = {
  display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", alignItems: "start", gap: 10, width: "100%", height: "auto",
  margin: 0, padding: "8px 6px", borderRadius: 0, textAlign: "left", whiteSpace: "normal", fontWeight: 400, lineHeight: 1.55,
  color: "var(--t1)",
};
const CLAMP_2: CSSProperties = { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" };

interface ActionsCtx {
  connectionId: string;
  canvasId?: string;
  schema?: string;
  triggers: ActionTrigger[];
  domain: string;
  onEvidence: (finding: RecordedFinding, domain: string) => void;
  onTriggersHint: () => void;
}

// ── A domain's findings ───────────────────────────────────────────────────────────

function FindingRow({ finding, ctx, first }: { finding: RecordedFinding; ctx: ActionsCtx; first: boolean }) {
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;   // gone at once; the store leaves it out of the next read
  return (
    <div style={first ? undefined : RULE}>
      <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(o => !o)} className="aug-fs-ui select-text"
        style={{ ...ROW_BUTTON, background: open ? "var(--bg-sel)" : undefined }}>
        <span style={open ? undefined : CLAMP_2}>{finding.finding}</span>
        <span style={{ color: "var(--t3)", paddingTop: 3 }}><Icon name={open ? "chevd" : "chevr"} size={12} /></span>
      </Button>
      {open && (
        <div style={{ padding: "4px 6px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="aug-fs-xs" style={{ ...ROW, gap: 6, ...MUTED }}>
            {finding.angle && <Chip>{finding.angle}</Chip>}
            {(finding.entities_involved ?? []).map((e, i) => (
              <span key={`${i}:${e}`} style={{ fontFamily: "var(--font-mono)", color: "var(--t2)" }}>{e}</span>
            ))}
            <span style={NUM}>
              {Math.round((finding.confidence ?? 0) * 100)}% confidence · novelty {finding.novelty}
              {finding.generated_at ? ` · found ${relTime(finding.generated_at)} ago` : ""}
            </span>
          </div>
          <FindingActions insight={finding} domain={ctx.domain} connectionId={ctx.connectionId} canvasId={ctx.canvasId}
            schema={ctx.schema} triggers={ctx.triggers} onEvidence={f => ctx.onEvidence(f, ctx.domain)}
            onTriggersHint={ctx.onTriggersHint} onDismissed={() => setDismissed(true)} />
        </div>
      )}
    </div>
  );
}

function DomainFindings({ ranked, query, ctx }: { ranked: RecordedFinding[]; query: string; ctx: ActionsCtx }) {
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? ranked.filter(f => f.finding.toLowerCase().includes(q) || (f.angle ?? "").toLowerCase().includes(q)) : ranked;
  }, [ranked, query]);
  if (shown.length === 0) {
    return <Empty>{query ? "No finding in this domain matches that search." : "No findings yet for this domain."}</Empty>;
  }
  const groups = BANDS.map(b => ({ band: b, rows: shown.filter(f => b.test(f.novelty)) })).filter(g => g.rows.length > 0);
  return (
    <div data-testid="domain-findings">
      {groups.map(({ band, rows }, g) => (
        <div key={band.id} data-testid={`findings-${band.id}`}>
          <GroupHead first={g === 0} name={<span title={band.title}>{band.name}</span>} count={rows.length} />
          {rows.map((f, i) => <FindingRow key={insightUid(f)} finding={f} ctx={ctx} first={i === 0} />)}
        </div>
      ))}
    </div>
  );
}

// ── The patterns that involve a domain ────────────────────────────────────────────

const PATTERN_KIND: Record<Pattern["type"], string> = {
  angle: "Recurring angle",
  entity: "Cross-domain driver",
  convergence: "High-novelty cluster",
};

type PatternFilter = "all" | Pattern["type"];
const PATTERN_FILTERS: PatternFilter[] = ["all", "angle", "entity", "convergence"];

function PatternRow({ pattern, domain, first, showKind }: { pattern: Pattern; domain: string; first: boolean; showKind: boolean }) {
  const [open, setOpen] = useState(false);
  const examples = withUniqueKeys(pattern.example_findings.filter(Boolean), f => f);
  return (
    <div style={first ? undefined : RULE}>
      <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(o => !o)} className="select-text"
        style={{ ...ROW_BUTTON, gridTemplateColumns: "minmax(0, 1fr) auto auto", alignItems: "center",
          background: open ? "var(--bg-sel)" : undefined }}>
        <span style={{ minWidth: 0 }}>
          <span className="aug-fs-ui" style={{ ...ROW, gap: 8 }}>
            <span style={{ fontWeight: 500 }}>{pattern.title}</span>
            {showKind && <Chip>{PATTERN_KIND[pattern.type] ?? pattern.type}</Chip>}
          </span>
          <span className="aug-fs-xs" title={pattern.description} style={{ ...MUTED, ...ONE_LINE, display: "block" }}>
            {pattern.description}
          </span>
        </span>
        <span className="aug-fs-xs" style={{ ...MUTED, ...NUM, textAlign: "right" }}>
          {countNoun(pattern.evidence_count, "finding")} · novelty {pattern.novelty}
        </span>
        <span style={{ color: "var(--t3)" }}><Icon name={open ? "chevd" : "chevr"} size={12} /></span>
      </Button>
      {open && (
        <div className="aug-fs-xs" style={{ padding: "4px 6px 12px", display: "flex", flexDirection: "column", gap: 8, ...MUTED }}>
          <div style={{ ...ROW, gap: 5 }}>
            <span>Domains</span>
            {pattern.domains.map(d => (
              <Chip key={d} tone={sameDomain(d, domain) ? "accent" : "plain"}>{d}</Chip>
            ))}
          </div>
          {pattern.entities.length > 0 && (
            <div style={{ ...ROW, gap: 6 }}>
              <span>Entities</span>
              {pattern.entities.slice(0, 8).map(e => (
                <span key={e} style={{ fontFamily: "var(--font-mono)", color: "var(--t2)" }}>{e}</span>
              ))}
              {pattern.entities.length > 8 && <span>+{pattern.entities.length - 8} more</span>}
            </div>
          )}
          {pattern.angles && pattern.angles.length > 0 && (
            <div style={{ ...ROW, gap: 5 }}>
              <span>Angles</span>
              {pattern.angles.map(a => <Chip key={a}>{a}</Chip>)}
            </div>
          )}
          {examples.map(([key, item]) => (
            <div key={key} className="aug-fs-sm" style={{ color: "var(--t2)", lineHeight: 1.55, paddingLeft: 10,
              borderLeft: "2px solid var(--b2)" }}>{item}</div>
          ))}
        </div>
      )}
    </div>
  );
}

function DomainPatterns({ connectionId, canvasId, schema, domain }: {
  connectionId: string;
  canvasId?: string;
  schema?: string;
  domain: string;
}) {
  const [patterns, setPatterns] = useState<Pattern[] | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<PatternFilter>("all");

  const read = useCallback((refresh: boolean) =>
    (canvasId ? getCanvasPatterns(canvasId, refresh) : getPatterns(connectionId, refresh, schema)).then(r => r.patterns ?? []),
  [connectionId, canvasId, schema]);

  const load = useCallback((refresh: boolean) => {
    if (refresh) setRefreshing(true);
    return read(refresh)
      .then(p => { setPatterns(p); setFailed(null); })
      .catch(e => setFailed(e instanceof Error ? e.message : String(e)))
      .finally(() => setRefreshing(false));
  }, [read]);

  useEffect(() => {
    let alive = true;
    read(false)
      .then(p => { if (alive) { setPatterns(p); setFailed(null); } })
      .catch(e => { if (alive) setFailed(e instanceof Error ? e.message : String(e)); });
    return () => { alive = false; };
  }, [read]);

  if (failed !== null && patterns === null) return <ReadFailed what="the patterns" error={failed} onRetry={() => void load(false)} />;
  if (patterns === null) return <SkeletonRows rows={3} />;

  const here = patterns.filter(p => p.domains.some(d => sameDomain(d, domain)));
  const shown = filter === "all" ? here : here.filter(p => p.type === filter);
  const elsewhere = patterns.length - here.length;
  const countOf = (f: PatternFilter) => (f === "all" ? here.length : here.filter(p => p.type === f).length);

  return (
    <div data-testid="domain-patterns" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ ...ROW, gap: 10 }}>
        <Segmented label="Pattern kind" value={filter} onChange={setFilter}
          options={PATTERN_FILTERS.map(f => ({ value: f, label: `${f === "all" ? "All" : PATTERN_KIND[f]} · ${countOf(f)}` }))} />
        <Button variant="outline" size="xs" disabled={refreshing} onClick={() => void load(true)} style={{ marginLeft: "auto" }}>
          {refreshing ? <><Pending /> Refreshing</> : "Refresh"}
        </Button>
      </div>
      {failed !== null && <ReadFailed what="the patterns again — these are the last ones read" error={failed} onRetry={() => void load(true)} />}
      {shown.length === 0 ? (
        <Empty>
          {patterns.length === 0
            ? "No patterns yet — they emerge as the explorer covers more domains and angles."
            : `No ${filter === "all" ? "" : `${PATTERN_KIND[filter].toLowerCase()} `}pattern involves ${domain}.`}
        </Empty>
      ) : (
        <div>{shown.map((p, i) => <PatternRow key={p.id} pattern={p} domain={domain} first={i === 0} showKind={filter === "all"} />)}</div>
      )}
      {elsewhere > 0 && <Empty>{countNoun(elsewhere, "more pattern")} {elsewhere === 1 ? "involves" : "involve"} other domains only.</Empty>}
    </div>
  );
}

// ── What a domain promoted to the org ─────────────────────────────────────────────

function DomainOrgKnowledge({ entries, failed, onRetry }: { entries: Promoted[]; failed: string | null; onRetry: () => void }) {
  if (failed !== null) return <ReadFailed what="what this domain promoted to the org" error={failed} onRetry={onRetry} />;
  if (entries.length === 0) return <Empty>Nothing from this domain is promoted to the org yet — a finding&apos;s actions can promote it.</Empty>;
  return (
    <div data-testid="domain-org">
      {entries.map((o, i) => (
        <div key={o.id} style={{ padding: "8px 6px", ...(i ? RULE : {}) }}>
          <div className="aug-fs-ui" style={{ color: "var(--t1)", lineHeight: 1.55 }}>{o.text}</div>
          <div className="aug-fs-xs" style={{ ...MUTED, ...NUM }}>
            {[o.angle, `${bandWord(o.novelty)} novelty`, `promoted ${relTime(o.promoted_at)} ago`].filter(Boolean).join(" · ")}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── A domain's page ───────────────────────────────────────────────────────────────

type DomainTab = "findings" | "patterns" | "org";

function DomainPage({ domain, data, org, orgFailed, onOrgRetry, ctx }: {
  domain: string;
  data: Domain;
  org: Promoted[];
  orgFailed: string | null;
  onOrgRetry: () => void;
  ctx: ActionsCtx;
}) {
  const [tab, setTab] = useState<DomainTab>("findings");
  const [query, setQuery] = useState("");
  const findings = findingsOf(data);
  const ranked = useMemo(() => [...findings].sort(byRank), [findings]);
  const promoted = useMemo(() => org.filter(o => sameDomain(o.domain, domain)), [org, domain]);
  const pct = coveragePct(data);

  const count = (n: number | null) => (n == null ? null : <span style={{ ...MUTED, ...NUM, marginLeft: 6 }}>{formatCount(n)}</span>);
  const tabs: { id: DomainTab; label: ReactNode }[] = [
    { id: "findings", label: <>Findings{count(findings.length)}</> },
    { id: "patterns", label: "Patterns" },
    { id: "org", label: <>Org knowledge{count(orgFailed !== null ? null : promoted.length)}</> },
  ];

  return (
    <div data-testid="profile-domain" style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
      <div>
        <h2 className="aug-fs-h1" style={{ margin: 0, fontWeight: 600, color: "var(--t1)", textTransform: "capitalize" }}>{domain}</h2>
        <div className="aug-fs-sm" style={{ ...MUTED, ...NUM, marginTop: 2 }}>
          {countNoun(findings.length, "finding")}
          {" · "}<span title={data.angles_covered.join(" · ") || undefined}>{countNoun(data.angles_covered.length, "angle")}</span>
          {" · "}<span title="The share of the explorer's query budget this domain has spent">explored {pct}%</span>
          {promoted.length > 0 && ` · ${formatCount(promoted.length)} promoted to the org`}
        </div>
      </div>

      <section aria-label={`${domain} findings, patterns and org knowledge`} style={CARD}>
        <TabStrip label={`${domain} views`} value={tab} onChange={setTab} size="1" tabs={tabs}
          trailing={tab === "findings" && (
            <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search findings…"
              aria-label={`Search the ${domain} findings`} style={{ width: 240 }} />
          )} />
        <div style={{ paddingTop: 10 }}>
          {tab === "findings" && <DomainFindings ranked={ranked} query={query} ctx={ctx} />}
          {tab === "patterns" && (
            <DomainPatterns connectionId={ctx.connectionId} canvasId={ctx.canvasId} schema={ctx.schema} domain={domain} />
          )}
          {tab === "org" && <DomainOrgKnowledge entries={promoted} failed={orgFailed} onRetry={onOrgRetry} />}
        </div>
      </section>
    </div>
  );
}

// ── The domain column ─────────────────────────────────────────────────────────────

/** One row of the column: a name, its count and a 6px bar of that count against the largest; the chosen row tinted. */
function ColumnRow({ name, count, max, on, meta, title, onClick }: {
  name: string; count?: number; max?: number; on: boolean; meta?: string; title?: string; onClick: () => void;
}) {
  return (
    <Button variant="ghost" aria-current={on ? "true" : undefined} title={title} onClick={onClick} className="aug-fs-sm"
      style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: "2px 8px", alignItems: "center", width: "100%",
        height: "auto", margin: 0, padding: "5px 8px", borderRadius: "var(--r2)", textAlign: "left", whiteSpace: "normal",
        fontWeight: on ? 500 : 400, color: "var(--t1)", background: on ? "var(--bg-sel)" : undefined }}>
      <span style={{ ...ONE_LINE, textTransform: "capitalize" }}>{name}</span>
      <span style={{ color: "var(--t2)", ...NUM }}>{count != null ? formatCount(count) : ""}</span>
      {meta && <span className="aug-fs-xs" style={{ ...MUTED, gridColumn: "1 / span 2" }}>{meta}</span>}
      {count != null && max != null && (
        <span aria-hidden style={{ gridColumn: "1 / span 2", height: 6, borderRadius: 3, background: "var(--bg-3)", overflow: "hidden" }}>
          <span style={{ display: "block", height: "100%", width: `${max > 0 ? (count / max) * 100 : 0}%`,
            background: on ? "var(--accent)" : "var(--chart-deemph)" }} />
        </span>
      )}
    </Button>
  );
}

// ── The layer ─────────────────────────────────────────────────────────────────────

export function ProfileLayer({ connectionId, canvasId, schema, workspaceId }: {
  connectionId: string;
  canvasId?: string;
  schema?: string;
  workspaceId?: string;
}) {
  const [domains, setDomains] = useState<Record<string, Domain> | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [org, setOrg] = useState<Promoted[]>([]);
  const [orgFailed, setOrgFailed] = useState<string | null>(null);
  const [triggers, setTriggers] = useState<ActionTrigger[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [evidence, setEvidence] = useState<{ finding: RecordedFinding; domain: string } | null>(null);
  const [reads, setReads] = useState(0);   // Refresh and Retry bump it

  useEffect(() => {
    let alive = true;
    getActionTriggers().then(t => { if (alive) setTriggers(t); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    (canvasId ? getCanvasDomainInsights(canvasId) : getDomainInsights(connectionId, schema))
      // The meta-domains ("Key Questions", "Synthesis") repeat a finding once per schema: dedupe at the boundary, so
      // the column's count, the page's count and its list all agree.
      .then(byDomain => { if (alive) { setDomains(dedupeDomainInsights(byDomain)); setFailed(null); } })
      .catch(e => { if (alive) { setDomains({}); setFailed(e instanceof Error ? e.message : String(e)); } });
    // Scoped like the rest of the layer; the org-wide view is the Org layer's. A failed read is said on the domain's
    // Org knowledge tab, never shown as nothing promoted.
    getOrgIntelligence(connectionId, schema)
      .then(promoted => { if (alive) { setOrg(promoted); setOrgFailed(null); } })
      .catch(e => { if (alive) { setOrg([]); setOrgFailed(e instanceof Error ? e.message : String(e)); } });
    return () => { alive = false; };
  }, [connectionId, canvasId, schema, reads]);

  const openEvidence = useCallback((finding: RecordedFinding, domain: string) => setEvidence({ finding, domain }), []);
  const showTriggersHint = useCallback(() => {
    toast.info("No delivery channel yet", { description: "Add a Slack or webhook trigger in Notifications to share findings." });
  }, []);

  const names = useMemo(() => Object.keys(domains ?? {}).sort(), [domains]);
  const visible = filter ? names.filter(d => d.toLowerCase().includes(filter.toLowerCase())) : names;
  const max = Math.max(1, ...names.map(d => (domains?.[d] ? findingsOf(domains[d]).length : 0)));
  const page = selected && domains?.[selected] ? selected : null;
  const reread = () => setReads(n => n + 1);

  return (
    <Page testId="profile">
      <EvidenceDrawer insight={evidence?.finding ?? null} domain={evidence?.domain ?? ""} connectionId={connectionId}
        onClose={() => setEvidence(null)} />
      <div style={{ display: "grid", gridTemplateColumns: "200px minmax(0, 1fr)", gap: 18, alignItems: "start" }}>
        <nav aria-label="Profile and domains" style={{ position: "sticky", top: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          <ColumnRow name="Overview" on={!page} onClick={() => setSelected(null)} title="What this business is, and its data" />
          <div style={{ marginTop: 12 }}>
            <Label right={domains && failed === null ? formatCount(names.length) : undefined}>Domains</Label>
          </div>
          {names.length > 8 && (
            <Input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter domains…" aria-label="Filter domains"
              style={{ marginBottom: 4 }} />
          )}
          {domains === null ? (
            <SkeletonRows rows={4} />
          ) : failed !== null ? (
            <ReadFailed what="the domains" error={failed} onRetry={reread} />
          ) : names.length === 0 ? (
            <Empty>No domains yet — the explorer files each finding under one as it runs.</Empty>
          ) : visible.length === 0 ? (
            <Empty>No domain matches.</Empty>
          ) : visible.map(d => {
            const promoted = org.filter(o => sameDomain(o.domain, d)).length;
            return (
              <ColumnRow key={d} name={d} count={findingsOf(domains[d]).length} max={max} on={page === d}
                meta={promoted > 0 ? `${formatCount(promoted)} promoted to the org` : undefined}
                title={`${d} · ${countNoun(findingsOf(domains[d]).length, "finding")}`} onClick={() => setSelected(d)} />
            );
          })}
          <Button variant="ghost" size="xs" onClick={reread} style={{ alignSelf: "flex-start", marginTop: 6, color: "var(--t2)" }}>
            Refresh
          </Button>
        </nav>

        {page && domains ? (
          <DomainPage key={page} domain={page} data={domains[page]} org={org} orgFailed={orgFailed} onOrgRetry={reread}
            ctx={{ connectionId, canvasId, schema, triggers, domain: page, onEvidence: openEvidence, onTriggersHint: showTriggersHint }} />
        ) : (
          <ProfilePanel connectionId={connectionId} canvasId={canvasId} schema={schema} workspaceId={workspaceId} />
        )}
      </div>
    </Page>
  );
}
