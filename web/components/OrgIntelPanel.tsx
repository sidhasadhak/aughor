"use client";

/**
 * Org — what the organisation knows, read as a page (the Intelligence workspace's Org tab), to CLARITY
 * (`aughor-v2/CLARITY.md`) and its rule for a knowledge view: prose and facts under headings, not tiles. One sheet: a
 * sentence saying what Org holds and what it is for, then the promoted findings by domain — each finding its own
 * sentence, one muted line of where it came from and when, and the door that takes it out. Nothing here waits on a
 * person, so there is no Needs you; no number is the point, so there are no figures.
 *
 * Org records one thing: findings promoted from a connection's Briefing (or a Data Canvas), and every deep analysis is
 * handed the five closest to its question (`knowledge/org_intelligence.py`). The design's Org layer also inferred people
 * and ownership, who to ask, and open disagreements over what a term means. Nothing stores any of that, so none of it is
 * drawn, and the sheet says so in one line rather than leaving a reader to look for it.
 *
 * `GET /org-intelligence` answers [] when its store cannot be read, so an outage reads the same as nothing promoted;
 * the empty sheet says that too. Only an HTTP failure is shown as a failed read.
 */
import { useEffect, useMemo, useState } from "react";

import { CARD, Chip, Empty, MUTED, Page, ROW, RULE } from "@/components/clarity/kit";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loading, ReadFailed } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";
import { deleteOrgInsight as takeOutOfOrg, getConnections, getOrgIntelligence, type Connection, type OrgInsight as Promoted }
  from "@/lib/api";
import { agoWords } from "@/lib/canvasList";
import { countNoun, formatCount, formatTimestamp } from "@/lib/format";
import { connectionLabel } from "@/lib/names";
import { localizeCurrency } from "@/lib/orgSettings";

/** The connection a finding was promoted from — read off the canvas key a Briefing's promotion writes when an older
 *  record carries no connection; "" for one promoted from a Data Canvas. */
function sourceOf(f: Promoted): string {
  if (f.connection_id) return f.connection_id;
  return f.canvas_id?.startsWith("conn:") ? f.canvas_id.slice(5) : "";
}

/** Prose the platform wrote, as a line: no markdown emphasis (nothing renders it here), the org's currency. */
const plain = (text: string) => localizeCurrency(text).replace(/\*+/g, "");

const domainOf = (f: Promoted) => f.domain?.trim() || "General";

export function OrgIntelPanel() {
  const [tick, setTick] = useState(0);
  const [read, setRead] = useState<{ tick: number; found: Promoted[] | null; error: string | null } | null>(null);
  const [conns, setConns] = useState<Connection[]>([]);
  const [search, setSearch] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getOrgIntelligence()
      .then(found => { if (alive) setRead({ tick, found, error: null }); })
      // a refresh that fails keeps what was read, and says it was not refreshed
      .catch(e => { if (alive) setRead(prev => ({ tick, found: prev?.found ?? null, error: String((e as Error)?.message || e) })); });
    return () => { alive = false; };
  }, [tick]);
  // A finding names its connection, never its id.
  useEffect(() => { getConnections().then(setConns).catch(() => {}); }, []);

  const all = read?.found ?? null;
  const refreshing = read?.tick !== tick;
  const query = search.trim().toLowerCase();
  const domains = useMemo(() => {
    const shown = (all ?? []).filter(f => !query || [f.text, f.domain, f.angle].some(v => (v || "").toLowerCase().includes(query)));
    const by = new Map<string, Promoted[]>();
    for (const f of [...shown].sort((a, b) => (b.promoted_at || "").localeCompare(a.promoted_at || ""))) {
      by.set(domainOf(f), [...(by.get(domainOf(f)) ?? []), f]);
    }
    return [...by].sort(([a], [b]) => a.localeCompare(b));
  }, [all, query]);
  const matched = domains.reduce((n, [, rows]) => n + rows.length, 0);
  // Said once: when every finding came from one connection, the sentence names it and no line repeats it.
  const sources = [...new Set((all ?? []).map(sourceOf))];
  const oneSource = sources.length === 1 ? sources[0] : null;

  const remove = async (id: string) => {
    setRemoving(id);
    try {
      await takeOutOfOrg(id);
      setRead(r => (r ? { ...r, found: r.found?.filter(f => f.id !== id) ?? null } : r));
    } catch (e) {
      // It stays listed: the server still holds it.
      toast.error("Not removed — it is still in Org", { description: String((e as Error)?.message || e).slice(0, 240) });
    } finally {
      setRemoving(null);
    }
  };

  const lead = oneSource
    ? `Findings promoted from ${connectionLabel(oneSource, conns)}'s Briefing.`
    : oneSource === "" ? "Findings promoted from a Data Canvas." : "Findings promoted from a connection's Briefing or a Data Canvas.";

  return (
    <Page testId="org-page">
      <article aria-label="Org" style={{ ...CARD, padding: "18px 22px" }}>
        <header style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
          <p className="aug-fs-ui" style={{ flex: "1 1 360px", margin: 0, color: "var(--t2)", lineHeight: 1.55 }}>
            {all && all.length > 0 ? lead : "Findings promoted from a connection's Briefing."} Every deep analysis is handed the five
            closest to its question.
          </p>
          <span style={{ ...ROW, flexWrap: "nowrap" }}>
            {query && all && <span className="aug-fs-xs" style={MUTED}>{formatCount(matched)} of {formatCount(all.length)}</span>}
            {all && all.length > 0 && (
              <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter findings"
                aria-label="Filter promoted findings" style={{ width: 220 }} />
            )}
            <Button variant="ghost" size="xs" disabled={refreshing && read !== null} onClick={() => setTick(t => t + 1)}>Refresh</Button>
          </span>
        </header>

        {read?.error && all && (
          <div className="aug-fs-xs" style={{ ...ROW, marginTop: 8 }}>
            <Chip tone="amber" title={read.error}>not refreshed — showing the last read</Chip>
          </div>
        )}

        {all === null ? (
          <div style={{ ...RULE, marginTop: 14, paddingTop: 14 }}>
            {read?.error
              ? <ReadFailed what="Org's findings" error={read.error} onRetry={() => setTick(t => t + 1)} />
              : <Loading what="Org's findings" />}
          </div>
        ) : all.length === 0 ? (
          <div data-testid="org-empty" style={{ ...RULE, marginTop: 14, paddingTop: 14 }}>
            <h3 className="aug-fs-h2" style={{ ...ROW, margin: 0, color: "var(--t1)", fontWeight: 600 }}>
              Nothing promoted yet
              <Chip title="Org's store answers an empty list when it cannot be read, so an outage looks the same as nothing promoted">
                or its store could not be read
              </Chip>
            </h3>
            <p className="aug-fs-sm" style={{ margin: "4px 0 0", color: "var(--t2)" }}>
              On a connection&apos;s Briefing, open a finding&apos;s ⋯ menu and choose Promote.
            </p>
          </div>
        ) : domains.length === 0 ? (
          <div style={{ ...RULE, marginTop: 14, paddingTop: 14 }}>
            <Empty>No promoted finding matches “{search.trim()}”.</Empty>
          </div>
        ) : domains.map(([domain, rows]) => (
          <section key={domain} aria-label={domain} data-testid="org-domain"
            style={{ ...RULE, marginTop: 14, paddingTop: 14, display: "flex", flexWrap: "wrap", gap: "6px 28px" }}>
            <h3 className="aug-fs-h2" style={{ flex: "0 0 180px", margin: 0, color: "var(--t1)", fontWeight: 600, lineHeight: 1.4 }}>
              {domain}
              <span className="aug-fs-xs" style={{ ...MUTED, display: "block", fontWeight: 400 }}>{countNoun(rows.length, "finding")}</span>
            </h3>
            <div style={{ flex: "1 1 420px", minWidth: 0, display: "flex", flexDirection: "column", gap: 10 }}>
              {rows.map(f => {
                const src = sourceOf(f);
                const facts: { text: string; title?: string }[] = [
                  { text: f.angle },
                  { text: oneSource === null ? `from ${src ? connectionLabel(src, conns) : "a Data Canvas"}` : "" },
                  { text: `promoted ${agoWords(f.promoted_at, Date.now())}${f.promoted_by && f.promoted_by !== "user" ? ` by ${f.promoted_by}` : ""}`,
                    title: formatTimestamp(f.promoted_at) },
                  { text: f.novelty != null ? `novelty ${f.novelty} of 5` : "",
                    title: "How new the finding was against its domain's other findings when it was found, 1 to 5" },
                ].filter(x => x.text);
                return (
                  <div key={f.id} data-testid="org-finding">
                    <p className="aug-fs-ui" style={{ margin: 0, color: "var(--t1)", lineHeight: 1.55 }}>{plain(f.text)}</p>
                    <div className="aug-fs-xs" style={{ ...MUTED, display: "flex", alignItems: "center", flexWrap: "wrap", gap: 8, marginTop: 2 }}>
                      <span style={{ minWidth: 0 }}>
                        {facts.map((x, i) => <span key={i} title={x.title}>{i ? " · " : ""}{x.text}</span>)}
                      </span>
                      <Button variant="ghost" size="xs" disabled={removing === f.id}
                        onClick={() => { void remove(f.id); }} title="Take this finding out of Org — no deep analysis is handed it again">
                        {removing === f.id ? "Removing…" : "Remove"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ))}

        <p className="aug-fs-xs" style={{ ...MUTED, margin: "18px 0 0" }}>
          Not recorded yet: people and owners, who to ask, and disagreements over what a term means.
        </p>
      </article>
    </Page>
  );
}
