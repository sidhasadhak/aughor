"use client";

/**
 * ProfileLayer.tsx — Intelligence › Profile: what Aughor knows about this business, beside the
 * domains its findings are filed under.
 *
 * Instrument's Profile redraw (#498) replaced the Hub, and the Hub's domain rail went with it —
 * the one place the findings could be read by domain. It is back (2026-09-14, the user's ask):
 * the rail lists each domain with its finding count, and a domain opens its own page — its
 * findings ranked by novelty, the patterns that involve it, and what was promoted to the org.
 * "Overview" is the profile itself (ProfilePanel), unchanged.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
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
  type ExplorationInsight,
  type OrgInsight,
  type Pattern,
} from "@/lib/api";
import { countNoun, formatCount, relTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Pending, SkeletonRows } from "@/components/ui/motion";
import { EvidenceDrawer, FindingActions } from "@/components/BriefingPanel";
import { ProfilePanel } from "@/components/ProfilePanel";

// ── How the Hub read a domain ─────────────────────────────────────────────────────

/** Novelty in the Hub's three bands: 5 and up is high, 3–4 mid, the rest low. */
function noveltyBand(n: number): { label: string; color: string } {
  if (n >= 5) return { label: "High", color: "var(--grn3)" };
  if (n >= 3) return { label: "Mid", color: "var(--amb3)" };
  return { label: "Low", color: "var(--t3)" };
}

/** The share of the explorer's query budget this domain has spent — what the Hub called "explored". */
function coveragePct(d: DomainInsights): number {
  if (!d.budget_cap) return 0;
  return Math.min(100, Math.round((d.queries_used / d.budget_cap) * 100));
}

/** Top findings first: novelty, then confidence. */
const byRank = (a: ExplorationInsight, b: ExplorationInsight) =>
  (b.novelty - a.novelty) || ((b.confidence ?? 0) - (a.confidence ?? 0));

const sameDomain = (a: string | undefined, b: string) => (a ?? "").toLowerCase() === b.toLowerCase();

/** A row that opens in place. The summary is the button; what it opens sits below it, so a
 *  finding's own actions are never buttons nested inside a button. */
const ROW_BUTTON: CSSProperties = {
  display: "flex", alignItems: "flex-start", justifyContent: "flex-start", gap: 10, width: "100%",
  height: "auto", borderRadius: 0, textAlign: "left", whiteSpace: "normal", fontWeight: 400, lineHeight: 1.55,
};
const CLAMP_2: CSSProperties = { display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" };

interface ActionsCtx {
  connectionId: string;
  canvasId?: string;
  schema?: string;
  triggers: ActionTrigger[];
  domain: string;
  onEvidence: (finding: ExplorationInsight, domain: string) => void;
  onTriggersHint: () => void;
}

function NoveltyTag({ novelty }: { novelty: number }) {
  const band = noveltyBand(novelty);
  return (
    <span className="aug-fs-xs" style={{
      flexShrink: 0, fontWeight: 600, letterSpacing: "0.04em", padding: "1px 6px", borderRadius: "var(--r1)",
      background: `color-mix(in srgb, ${band.color} 14%, transparent)`, color: band.color,
    }}>{band.label}</span>
  );
}

function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="aug-fs-xs" style={{
      display: "inline-flex", alignItems: "center", gap: 5, color: "var(--t2)",
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: "3px 9px",
    }}>{children}</span>
  );
}

// ── A domain's findings ───────────────────────────────────────────────────────────

function FindingRow({ finding, ctx }: { finding: ExplorationInsight; ctx: ActionsCtx }) {
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;   // gone at once; the store leaves it out of the next read
  return (
    <div style={{ borderBottom: "1px solid var(--b0)" }}>
      <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(o => !o)}
        className="aug-fs-sm select-text" style={{ ...ROW_BUTTON, padding: "10px 16px", color: "var(--t1)" }}>
        <NoveltyTag novelty={finding.novelty} />
        <span style={{ flex: 1, minWidth: 0, ...(open ? {} : CLAMP_2) }}>{finding.finding}</span>
        <span aria-hidden className="aug-fs-xs" style={{ flexShrink: 0, color: "var(--t3)" }}>{open ? "▴" : "▾"}</span>
      </Button>
      {open && (
        <div style={{ padding: "0 16px 12px", display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="aug-fs-xs" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, color: "var(--t3)" }}>
            {finding.angle && (
              <span style={{ background: "var(--bg-2)", borderRadius: "var(--r1)", padding: "1px 6px" }}>{finding.angle}</span>
            )}
            {finding.entities_involved?.map(e => (
              <span key={e} style={{
                color: "var(--blue4)", background: "color-mix(in srgb, var(--blue4) 10%, transparent)",
                borderRadius: "var(--r1)", padding: "1px 6px",
              }}>{e}</span>
            ))}
            <span>
              confidence {Math.round((finding.confidence ?? 0) * 100)}%
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

// ── The patterns that involve a domain ────────────────────────────────────────────

const PATTERN_KIND: Record<Pattern["type"], { label: string; color: string; glyph: string }> = {
  angle:       { label: "Recurring angle",      color: "var(--blue4)", glyph: "↻" },
  entity:      { label: "Cross-domain driver",  color: "var(--vio3)",  glyph: "⊕" },
  convergence: { label: "High-novelty cluster", color: "var(--grn3)",  glyph: "◎" },
};

type PatternFilter = "all" | Pattern["type"];
const PATTERN_FILTERS: PatternFilter[] = ["all", "angle", "entity", "convergence"];

function PatternCard({ pattern, domain }: { pattern: Pattern; domain: string }) {
  const [open, setOpen] = useState(false);
  const kind = PATTERN_KIND[pattern.type] ?? PATTERN_KIND.angle;
  return (
    <div style={{
      background: "var(--bg-1)", border: "1px solid var(--b1)", borderLeft: `3px solid ${kind.color}`,
      borderRadius: "var(--r3)", overflow: "hidden",
    }}>
      <Button variant="ghost" aria-expanded={open} onClick={() => setOpen(o => !o)}
        className="select-text" style={{ ...ROW_BUTTON, padding: "12px 16px" }}>
        <span className="aug-fs-xs" style={{
          flexShrink: 0, marginTop: 1, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em",
          padding: "2px 6px", borderRadius: "var(--r1)",
          background: `color-mix(in srgb, ${kind.color} 14%, transparent)`, color: kind.color,
        }}>{kind.glyph} {kind.label}</span>
        <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
          <span className="aug-fs-sm" style={{ fontWeight: 600, color: "var(--t1)" }}>{pattern.title}</span>
          <span className="aug-fs-xs" style={{ color: "var(--t3)", lineHeight: 1.5 }}>{pattern.description}</span>
        </span>
        <span className="aug-fs-xs" style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, fontWeight: 600 }}>
          <span style={{ color: "var(--t2)" }}>{countNoun(pattern.evidence_count, "finding")}</span>
          <span style={{ color: `color-mix(in srgb, var(--grn3) ${Math.min(100, pattern.novelty * 12)}%, var(--amb3))` }}>
            novelty {pattern.novelty}
          </span>
        </span>
        <span aria-hidden className="aug-fs-xs" style={{ flexShrink: 0, color: "var(--t3)" }}>{open ? "▴" : "▾"}</span>
      </Button>
      {open && (
        <div className="aug-fs-xs" style={{
          borderTop: "1px solid var(--b0)", padding: "12px 16px", display: "flex", flexDirection: "column", gap: 10, color: "var(--t3)",
        }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5 }}>
            <span>Domains:</span>
            {pattern.domains.map(d => (
              <span key={d} style={{
                padding: "1px 7px", borderRadius: "var(--r1)", textTransform: "capitalize",
                background: sameDomain(d, domain) ? `color-mix(in srgb, ${kind.color} 16%, transparent)` : "var(--bg-2)",
                color: sameDomain(d, domain) ? kind.color : "var(--t3)",
              }}>{d}</span>
            ))}
          </div>
          {pattern.entities.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5 }}>
              <span>Entities:</span>
              {pattern.entities.slice(0, 8).map(e => (
                <span key={e} style={{ padding: "1px 6px", borderRadius: "var(--r1)", background: "var(--bg-2)", fontFamily: "var(--font-mono)" }}>{e}</span>
              ))}
            </div>
          )}
          {pattern.angles && pattern.angles.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5 }}>
              <span>Angles:</span>
              {pattern.angles.map(a => (
                <span key={a} style={{ padding: "1px 6px", borderRadius: "var(--r1)", color: "var(--blue4)", background: "color-mix(in srgb, var(--blue3) 10%, transparent)" }}>{a}</span>
              ))}
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <span className="aug-brief-eyebrow">Example findings</span>
            {pattern.example_findings.filter(Boolean).map((f, i) => (
              <div key={i} style={{
                color: "var(--t2)", lineHeight: 1.55, padding: "6px 10px", background: "var(--bg-2)",
                borderRadius: "var(--r2)", borderLeft: `2px solid color-mix(in srgb, ${kind.color} 27%, transparent)`,
              }}>“{f}”</div>
            ))}
          </div>
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
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<PatternFilter>("all");

  const read = useCallback((refresh: boolean) =>
    (canvasId ? getCanvasPatterns(canvasId, refresh) : getPatterns(connectionId, refresh, schema))
      .then(r => r.patterns ?? [])
      .catch(() => [] as Pattern[]),
  [connectionId, canvasId, schema]);

  useEffect(() => {
    let alive = true;
    read(false).then(p => { if (alive) setPatterns(p); });
    return () => { alive = false; };
  }, [read]);

  const refresh = async () => {
    setRefreshing(true);
    setPatterns(await read(true));
    setRefreshing(false);
  };

  if (patterns === null) return <div style={{ padding: "14px 20px" }}><SkeletonRows rows={3} /></div>;

  const here = patterns.filter(p => p.domains.some(d => sameDomain(d, domain)));
  const shown = filter === "all" ? here : here.filter(p => p.type === filter);
  const elsewhere = patterns.length - here.length;

  return (
    <div style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div className="aug-segmented" role="group" aria-label="Pattern kind">
          {PATTERN_FILTERS.map(f => (
            <Button key={f} variant="ghost" className="aug-seg-item" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? `All (${here.length})` : f[0].toUpperCase() + f.slice(1)}
            </Button>
          ))}
        </div>
        <span className="aug-brief-meta" style={{ marginLeft: "auto" }}>{countNoun(shown.length, "pattern")} in this domain</span>
        <Button variant="outline" size="xs" disabled={refreshing} onClick={refresh}>
          {refreshing ? <><Pending /> Refreshing</> : "Refresh"}
        </Button>
      </div>
      {shown.length === 0 ? (
        <p className="aug-brief-note">
          {patterns.length === 0
            ? "No patterns detected yet. They emerge as the explorer covers more domains and angles."
            : `No ${filter === "all" ? "" : `${filter} `}patterns involve the ${domain} domain.`}
        </p>
      ) : shown.map(p => <PatternCard key={p.id} pattern={p} domain={domain} />)}
      {elsewhere > 0 && (
        <p className="aug-brief-note">
          {countNoun(elsewhere, "other pattern")} {elsewhere === 1 ? "involves" : "involve"} other domains only — open one from the rail.
        </p>
      )}
    </div>
  );
}

// ── What a domain promoted to the org ─────────────────────────────────────────────

function DomainOrgKnowledge({ entries }: { entries: OrgInsight[] }) {
  if (entries.length === 0) {
    return (
      <p className="aug-brief-note" style={{ padding: "14px 20px" }}>
        Nothing from this domain has been promoted to the org yet. A finding&apos;s actions can promote it.
      </p>
    );
  }
  return (
    <div style={{ padding: "14px 20px", display: "flex", flexDirection: "column", gap: 8 }}>
      {entries.map(o => {
        const band = noveltyBand(o.novelty);
        return (
          <div key={o.id} style={{
            background: "var(--bg-1)", border: "1px solid var(--b1)", borderRadius: "var(--r3)",
            padding: "10px 14px", display: "flex", flexDirection: "column", gap: 6,
          }}>
            <div className="aug-fs-xs" style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--t3)" }}>
              {o.angle && <span>{o.angle}</span>}
              <span style={{ marginLeft: "auto", color: band.color, fontWeight: 600 }}>{band.label} novelty</span>
            </div>
            <p className="aug-fs-sm" style={{ margin: 0, color: "var(--t2)", lineHeight: 1.55 }}>{o.text}</p>
            <span className="aug-fs-xs" style={{ color: "var(--t3)" }}>promoted {relTime(o.promoted_at)} ago</span>
          </div>
        );
      })}
    </div>
  );
}

// ── A domain's page ───────────────────────────────────────────────────────────────

type DomainTab = "findings" | "patterns" | "org";

function DomainPage({ domain, data, org, ctx, onBack }: {
  domain: string;
  data: DomainInsights;
  org: OrgInsight[];
  ctx: ActionsCtx;
  onBack: () => void;
}) {
  const [tab, setTab] = useState<DomainTab>("findings");
  const [query, setQuery] = useState("");
  const findings = data.insights;
  const ranked = useMemo(() => [...findings].sort(byRank), [findings]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? ranked.filter(f => f.finding.toLowerCase().includes(q) || (f.angle ?? "").toLowerCase().includes(q)) : ranked;
  }, [ranked, query]);
  const promoted = useMemo(() => org.filter(o => sameDomain(o.domain, domain)), [org, domain]);
  const high = findings.filter(f => f.novelty >= 5).length;
  const mid = findings.filter(f => f.novelty >= 3 && f.novelty < 5).length;
  const low = findings.length - high - mid;
  const pct = coveragePct(data);

  const tabs: { id: DomainTab; label: string }[] = [
    { id: "findings", label: `Findings (${formatCount(findings.length)})` },
    { id: "patterns", label: "Patterns" },
    { id: "org", label: `Org knowledge (${promoted.length})` },
  ];

  return (
    <div className="aug-profile-domain-page">
      <div className="aug-brief-strip">
        <Button variant="ghost" size="xs" onClick={onBack}>← Overview</Button>
        <span className="aug-fs-h2" style={{
          minWidth: 0, fontWeight: 600, color: "var(--t1)", textTransform: "capitalize",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{domain}</span>
        <span className="aug-brief-eyebrow">Domain</span>
      </div>

      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, padding: "10px 16px", borderBottom: "1px solid var(--b1)" }}>
        <Pill><strong style={{ color: "var(--t1)" }}>{formatCount(findings.length)}</strong> findings</Pill>
        <Pill>
          <span style={{ color: "var(--grn3)", fontWeight: 600 }}>{high}H</span>
          <span style={{ color: "var(--amb3)", fontWeight: 600 }}>{mid}M</span>
          <span style={{ color: "var(--t3)", fontWeight: 600 }}>{low}L</span>
        </Pill>
        <Pill><strong style={{ color: "var(--t1)" }}>{data.angles_covered.length}</strong> angles</Pill>
        <Pill>
          explored
          <span aria-hidden style={{ display: "inline-block", width: 54, height: 4, borderRadius: 2, overflow: "hidden", background: "var(--bg-3)" }}>
            <span style={{ display: "block", width: `${pct}%`, height: "100%", background: pct > 70 ? "var(--grn3)" : pct > 40 ? "var(--amb3)" : "var(--b3)" }} />
          </span>
          <strong style={{ color: "var(--t1)" }}>{pct}%</strong>
        </Pill>
        {promoted.length > 0 && (
          <Pill><span style={{ color: "var(--vio3)", fontWeight: 600 }}>◈ {promoted.length}</span> promoted to the org</Pill>
        )}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid var(--b1)" }}>
        <div className="aug-segmented" role="tablist" aria-label={`${domain} views`}>
          {tabs.map(t => (
            <Button key={t.id} variant="ghost" role="tab" className="aug-seg-item" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
            </Button>
          ))}
        </div>
        {tab === "findings" && (
          <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search findings…"
            aria-label={`Search the ${domain} findings`} className="aug-fs-sm" style={{ marginLeft: "auto", width: 240, height: 26 }} />
        )}
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: "auto" }}>
        {tab === "findings" && (shown.length === 0 ? (
          <p className="aug-brief-note" style={{ padding: "14px 20px" }}>
            {query ? "No finding in this domain matches that search." : "No findings yet for this domain."}
          </p>
        ) : shown.map(f => <FindingRow key={insightUid(f)} finding={f} ctx={ctx} />))}
        {tab === "patterns" && (
          <DomainPatterns connectionId={ctx.connectionId} canvasId={ctx.canvasId} schema={ctx.schema} domain={domain} />
        )}
        {tab === "org" && <DomainOrgKnowledge entries={promoted} />}
      </div>
    </div>
  );
}

// ── The layer ─────────────────────────────────────────────────────────────────────

export function ProfileLayer({ connectionId, canvasId, schema, workspaceId }: {
  connectionId: string;
  canvasId?: string;
  schema?: string;
  workspaceId?: string;
}) {
  const [domains, setDomains] = useState<Record<string, DomainInsights> | null>(null);
  const [failed, setFailed] = useState(false);
  const [org, setOrg] = useState<OrgInsight[]>([]);
  const [triggers, setTriggers] = useState<ActionTrigger[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [evidence, setEvidence] = useState<{ finding: ExplorationInsight; domain: string } | null>(null);
  const [hint, setHint] = useState<string | null>(null);
  const [reads, setReads] = useState(0);   // Refresh bumps it
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    getActionTriggers().then(t => { if (alive) setTriggers(t); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      canvasId ? getCanvasDomainInsights(canvasId) : getDomainInsights(connectionId, schema),
      // Scoped like the rest of the layer; the org-wide view is the Org layer's.
      getOrgIntelligence(connectionId, schema).catch(() => [] as OrgInsight[]),
    ]).then(([byDomain, promoted]) => {
      if (!alive) return;
      // The meta-domains ("Key Questions", "Synthesis") repeat a finding once per schema: dedupe at
      // the boundary, so the rail's count, the page's count and its list all agree.
      setDomains(dedupeDomainInsights(byDomain));
      setOrg(promoted);
      setFailed(false);
    }).catch(() => {
      if (!alive) return;
      setDomains({});
      setFailed(true);
    });
    return () => { alive = false; };
  }, [connectionId, canvasId, schema, reads]);

  useEffect(() => () => { if (hintTimer.current) clearTimeout(hintTimer.current); }, []);

  const openEvidence = useCallback((finding: ExplorationInsight, domain: string) => setEvidence({ finding, domain }), []);
  const showTriggersHint = useCallback(() => {
    setHint("No delivery channel yet — add a Slack or webhook trigger in Notifications to share findings.");
    if (hintTimer.current) clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => setHint(null), 5000);
  }, []);

  const names = useMemo(() => Object.keys(domains ?? {}).sort(), [domains]);
  const visible = filter ? names.filter(d => d.toLowerCase().includes(filter.toLowerCase())) : names;
  const page = selected && domains?.[selected] ? selected : null;

  return (
    <div className="aug-profile-layer">
      <EvidenceDrawer insight={evidence?.finding ?? null} domain={evidence?.domain ?? ""} connectionId={connectionId}
        onClose={() => setEvidence(null)} />
      {hint && <div role="status" className="aug-profile-hint aug-fs-sm">{hint}</div>}

      <nav className="aug-profile-domains" aria-label="Profile and domains">
        <div className="aug-nav-section">
          <Button variant="ghost" className={cn("aug-nav-item", !page && "active")} aria-current={page ? undefined : "true"}
            style={{ justifyContent: "flex-start" }} onClick={() => setSelected(null)}>
            Overview
          </Button>
        </div>
        <div className="aug-nav-group" style={{ paddingTop: 8 }}>
          Domains
          {domains && !failed && <span className="aug-nav-badge">{names.length}</span>}
        </div>
        {names.length > 8 && (
          <div style={{ padding: "2px 10px 6px" }}>
            <Input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter domains…"
              aria-label="Filter domains" className="aug-fs-xs" style={{ height: 24 }} />
          </div>
        )}
        <div className="aug-profile-domains-list">
          {domains === null ? (
            <div style={{ padding: "4px 14px" }}><SkeletonRows rows={4} /></div>
          ) : failed ? (
            <p className="aug-brief-note" style={{ padding: "4px 14px" }}>The domains could not be read.</p>
          ) : names.length === 0 ? (
            <p className="aug-brief-note" style={{ padding: "4px 14px" }}>No domains yet. The explorer files each finding under a domain as it runs.</p>
          ) : visible.map(d => {
            const promoted = org.filter(o => sameDomain(o.domain, d)).length;
            return (
              <Button key={d} variant="ghost" className={cn("aug-nav-item", page === d && "active")}
                aria-current={page === d ? "true" : undefined} style={{ justifyContent: "flex-start" }}
                title={d} onClick={() => setSelected(d)}>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", textTransform: "capitalize" }}>{d}</span>
                {promoted > 0 && (
                  <span title={`${countNoun(promoted, "finding")} promoted to the org`}
                    style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, background: "var(--vio3)" }} />
                )}
                <span className="aug-nav-badge">{formatCount(domains[d].insights.length)}</span>
              </Button>
            );
          })}
        </div>
        <div className="aug-nav-foot">
          <Button variant="ghost" size="xs" style={{ width: "100%" }} onClick={() => setReads(n => n + 1)}>Refresh</Button>
        </div>
      </nav>

      {page && domains ? (
        <DomainPage key={page} domain={page} data={domains[page]} org={org} onBack={() => setSelected(null)}
          ctx={{ connectionId, canvasId, schema, triggers, domain: page, onEvidence: openEvidence, onTriggersHint: showTriggersHint }} />
      ) : (
        <ProfilePanel connectionId={connectionId} canvasId={canvasId} schema={schema} workspaceId={workspaceId} />
      )}
    </div>
  );
}
