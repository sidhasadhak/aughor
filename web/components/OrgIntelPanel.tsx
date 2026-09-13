"use client";

/**
 * OrgIntelPanel — what the organisation shares (Aughor Intelligence · 08 Org).
 *
 * Drawn from the one thing Org records: findings promoted from a connection so every workspace can
 * read them, as a ledger — domain, the finding with the angle it came from, novelty, when it was
 * promoted. The design's Org layer also infers people and ownership, who to ask, and open
 * disagreements between people's readings of a term. Nothing stores any of that, so none of it is
 * drawn, and the rail says so in a sentence rather than leaving a reader to look for it.
 *
 * `GET /org-intelligence` reads the vector store and answers [] when that store fails, so an outage
 * reads the same as nothing promoted. Only an HTTP failure is shown as an error.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/motion";
import { ErrorState } from "@/components/ui/states";
import { deleteOrgInsight, getOrgIntelligence, type OrgInsight } from "@/lib/api";
import { countNoun, formatTimestamp, relTime } from "@/lib/format";

export function OrgIntelPanel() {
  const [insights, setInsights] = useState<OrgInsight[]>([]);
  const [loading, setLoading]   = useState(true);
  const [failed, setFailed]     = useState(false);
  const [search, setSearch]     = useState("");
  const [removing, setRemoving] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setInsights(await getOrgIntelligence());
    } catch {
      setInsights([]);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const remove = useCallback(async (id: string) => {
    setRemoving(id);
    try {
      await deleteOrgInsight(id);
      setInsights(prev => prev.filter(i => i.id !== id));
    } catch {
      // It stays listed: the server still holds it.
    } finally {
      setRemoving(null);
    }
  }, []);

  const query = search.trim().toLowerCase();
  const shown = useMemo(() => {
    const list = query
      ? insights.filter(i => [i.text, i.domain, i.angle].some(v => (v || "").toLowerCase().includes(query)))
      : insights;
    return [...list].sort((a, b) =>
      (a.domain || "General").localeCompare(b.domain || "General") || (b.promoted_at || "").localeCompare(a.promoted_at || ""));
  }, [insights, query]);
  const domainCount = useMemo(() => new Set(insights.map(i => i.domain || "General")).size, [insights]);

  return (
    <div className="aug-ledger">
      <div className="aug-ledger-main">
        <div className="aug-ledger-bar">
          <span className="aug-brief-eyebrow">Org</span>
          {!loading && !failed && (
            <span className="aug-ledger-meta aug-org-meta">
              {countNoun(insights.length, "promoted finding")} · {countNoun(domainCount, "domain")}
            </span>
          )}
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Filter findings"
            aria-label="Filter promoted findings" className="aug-input aug-org-filter" />
          <Button variant="ghost" size="xs" onClick={() => { void load(); }}>Refresh</Button>
        </div>

        {loading ? (
          <div className="aug-ledger-pad"><SkeletonRows rows={6} /></div>
        ) : failed ? (
          <div className="aug-ledger-pad">
            <ErrorState kind="Org failed" what="The promoted findings could not be read."
              doors={[{ label: "Try again", onClick: () => { void load(); }, primary: true }]} />
          </div>
        ) : insights.length === 0 ? (
          <div className="aug-ledger-pad">
            <EmptyState icon="spark" title="Nothing promoted yet">
              A finding reaches Org when someone promotes it: open a finding on a connection&apos;s Briefing and choose
              Promote to Org from its menu. Every workspace reads what is promoted here.
            </EmptyState>
          </div>
        ) : (
          <>
            <div className="aug-ledger-scroll">
              <table className="aug-dt aug-ledger-table">
                <thead>
                  <tr>
                    <th className="aug-org-col-domain">domain</th>
                    <th>finding · and the angle it came from</th>
                    <th className="num aug-org-col-novelty">novelty</th>
                    <th className="num aug-org-col-when">promoted</th>
                    <th className="aug-org-col-door"><span className="sr-only">Remove</span></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(i => (
                    <tr key={i.id}>
                      <td className="aug-org-domain">{i.domain || "General"}</td>
                      <td className="aug-ledger-claim">
                        <span className="aug-ledger-text">{i.text}</span>
                        {(i.angle || i.canvas_id) && (
                          <span className="aug-ledger-query">
                            {[i.angle, i.canvas_id ? `canvas ${i.canvas_id.slice(0, 8)}` : ""].filter(Boolean).join(" · ")}
                          </span>
                        )}
                      </td>
                      <td className="num aug-org-novelty">{i.novelty == null ? "—" : i.novelty.toFixed(1)}</td>
                      <td className="num aug-ledger-when" title={formatTimestamp(i.promoted_at)}>{relTime(i.promoted_at)}</td>
                      <td className="aug-org-door">
                        <Button variant="ghost" size="xs" disabled={removing === i.id}
                          onClick={() => { void remove(i.id); }} title="Remove this finding from Org">
                          {removing === i.id ? "Removing" : "Remove"}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {shown.length === 0 && (
                <p className="aug-ledger-empty">No promoted finding matches “{search.trim()}”.</p>
              )}
            </div>
            <div className="aug-ledger-foot">
              <span>showing {shown.length} of {insights.length}</span>
            </div>
          </>
        )}
      </div>

      <aside className="aug-inspector" aria-label="What Org holds">
        <div className="aug-inspector-head"><span className="aug-brief-eyebrow">What Org holds</span></div>
        <div className="aug-inspector-sec">
          <p className="aug-inspector-note">
            Findings promoted from a connection, so every workspace can read them. Remove takes a finding out of Org.
          </p>
          <p className="aug-inspector-note">
            Org does not infer people, owners, who to ask, or disagreements over what a term means — nothing records
            them yet.
          </p>
        </div>
      </aside>
    </div>
  );
}
