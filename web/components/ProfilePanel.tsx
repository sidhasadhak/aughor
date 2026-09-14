"use client";

/**
 * ProfilePanel — what Aughor knows about this business (Aughor Intelligence · 02 Profile).
 *
 * Instrument-dense, not an artefact: three numbered sections — what this business is, the data
 * profile by table, and what a blank means in a column — beside a rail of the governed metrics and
 * the status columns the explorer mapped. §03 carries forward the one thing the old Hub's
 * exploration panel knew that nothing else shows: the explorer's null meanings.
 *
 * Drawn only from stored data. Left out, because nothing records it:
 *   - a confidence and a "decided by" per table, and per fact except the industry guess;
 *   - channels, distribution centres, a fiscal week, revenue recognition, a returns window;
 *   - a "disputed" metric state — a metric is draft, proposed, approved or deprecated;
 *   - a lifecycle ORDER: the explorer stores a status column's values and, only when a table has a
 *     key and a timestamp, its transitions — so the rail says "status columns" and draws no arrows;
 *   - a profiling-run count, and Re-profile / Correct doors: no endpoint re-profiles on demand, the
 *     profile rebuild is an LLM call, and nothing corrects a profile in place.
 * A human setting wins over inference only where org settings say so (industry, currency, a fiscal
 * year that does not start in January), and the chips say which is which.
 *
 * Reads: /business-profile, /org-settings/effective and /metrics are pure. The schema profile may
 * open a warehouse connection when its cache has expired, and /findings runs an information-schema
 * query when given a schema — reads, never writes and never an LLM call.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { SkeletonRows } from "@/components/ui/motion";
import {
  getBusinessProfile, getEffectiveSettings, getExplorationFindings, getMetrics, getSchemaProfile,
  type BusinessProfileResponse, type ExplorationFindings, type Metric, type OrgSettings, type SchemaProfile,
} from "@/lib/api";
import { countNoun, formatCount, formatTimestamp, pct, relTime } from "@/lib/format";

type Load<T> = { state: "loading" } | { state: "ready"; data: T } | { state: "failed" };

/** One read per source, each failing on its own — a missing metric store must not blank the profile. */
function useLoad<T>(read: () => Promise<T>, deps: unknown[]): Load<T> {
  const [load, setLoad] = useState<Load<T>>({ state: "loading" });
  useEffect(() => {
    let alive = true;
    setLoad({ state: "loading" });
    read()
      .then(data => { if (alive) setLoad({ state: "ready", data }); })
      .catch(() => { if (alive) setLoad({ state: "failed" }); });
    return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return load;
}

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

/** What the explorer found a blank to mean (its null-meaning phase). "not_applicable" (never blank)
 *  and "unknown" say nothing about a blank, so they are not listed. */
const BLANK: Record<string, string> = {
  pending:                 "an event that has not happened yet",
  not_applicable_terminal: "not applicable once terminal",
  missing:                 "a data-quality gap",
  mixed:                   "more than one thing",
};

/** An inference Aughor holds (✓), a human setting or an unsure inference (◈), or an inference with
 *  no confidence recorded (no mark). Facts borrow the guard chip's drawing because the design draws
 *  them in that grammar, but a fact is not a guard verdict, so it is not a GuardChip. */
type Mark = "held" | "human" | "unsure" | "plain";

function FactChip({ mark, title, children }: { mark: Mark; title?: string; children: ReactNode }) {
  const cls = mark === "held" ? "aug-guard aug-guard-passed" : mark === "plain" ? "aug-guard" : "aug-guard aug-guard-warned";
  return (
    <span className={cls} title={title}>
      {mark === "held" && <span aria-hidden>✓</span>}
      {(mark === "human" || mark === "unsure") && <span aria-hidden>◈</span>}
      {children}
    </span>
  );
}

function metricState(status?: string): ReactNode {
  if (status === "approved") return <FactChip mark="held">approved</FactChip>;
  if (status === "proposed") return <FactChip mark="unsure">proposed</FactChip>;
  return <FactChip mark="plain">{status || "draft"}</FactChip>;
}

/** At or above this the industry guess is held; below it the chip says it is an inference. */
const HELD = 0.86;

function Section({ children }: { children: ReactNode }) {
  return (
    <section className="aug-brief-sec">
      <div className="aug-brief-body">{children}</div>
    </section>
  );
}

export function ProfilePanel({ connectionId, canvasId, schema, workspaceId }: {
  connectionId: string;
  canvasId?:    string;
  schema?:      string;
  workspaceId?: string;
}) {
  const profile  = useLoad<BusinessProfileResponse>(() => getBusinessProfile(connectionId, schema), [connectionId, schema]);
  const settings = useLoad<OrgSettings>(() => getEffectiveSettings(workspaceId), [workspaceId]);
  const tables   = useLoad<SchemaProfile>(() => getSchemaProfile(connectionId), [connectionId]);
  const metrics  = useLoad<Metric[]>(() => getMetrics(), []);
  const findings = useLoad<ExplorationFindings>(() => getExplorationFindings(connectionId, schema), [connectionId, schema]);

  const p = profile.state === "ready" && profile.data.available ? profile.data.profile ?? null : null;
  const generatedAt = profile.state === "ready" ? profile.data.generated_at ?? null : null;
  const org = settings.state === "ready" ? settings.data : null;

  const facts = useMemo(() => {
    const out: { key: string; mark: Mark; text: string; title?: string; changes?: boolean }[] = [];
    if (org?.industry) {
      const changes = !p?.industry || p.industry !== org.industry;
      out.push({ key: "industry", mark: "human", text: `human: industry ${org.industry}`, changes,
        title: changes && p?.industry ? `Aughor inferred ${p.industry}; the org setting wins`
          : changes ? "Set in org settings" : "Set in org settings, and the inference agrees" });
    } else if (p?.industry) {
      const held = p.confidence >= HELD;
      out.push({ key: "industry", mark: held ? "held" : "unsure", text: held ? p.industry : `${p.industry}, inferred`,
        title: `Industry inferred at confidence ${p.confidence.toFixed(2)}` });
    }
    if (p?.business_model) {
      out.push({ key: "model", mark: "plain", text: p.business_model, title: "Inferred; no confidence is recorded for it" });
    }
    if (org?.currency_code) {
      const changes = !p?.currency_code || p.currency_code !== org.currency_code;
      out.push({ key: "currency", mark: "human", text: `human: currency ${org.currency_code}`, changes,
        title: changes && p?.currency_code ? `Aughor inferred ${p.currency_code}; the org setting wins`
          : changes ? "Set in org settings" : "Set in org settings, and the inference agrees" });
    } else if (p?.currency_code) {
      out.push({ key: "currency", mark: "plain", text: `currency ${p.currency_code}`,
        title: p.currency_code === "USD" ? "USD is also what the profile says when nothing indicates otherwise" : "Inferred" });
    }
    // A January start is also what an unset setting reads as, so only another month is a human decision.
    if (org && org.fiscal_year_start_month > 1) {
      out.push({ key: "fy", mark: "human", text: `human: fiscal year starts ${MONTHS[org.fiscal_year_start_month - 1]}`,
        title: "Set in org settings", changes: true });
    }
    return out;
  }, [p, org]);
  // "Corrected" only when a human setting changed or added something; one that restates the inference
  // confirms it.
  const corrected = facts.some(f => f.changes);
  const confirmed = !corrected && facts.some(f => f.mark === "human");

  const tableRows = useMemo(() => {
    if (tables.state !== "ready" || !tables.data.available) return [];
    const prefix = schema ? `${schema}.` : null;
    const nulls = new Map<string, { sum: number; n: number }>();
    for (const c of tables.data.columns) {
      if (typeof c.null_rate !== "number") continue;   // an unmeasured column is not a zero
      const acc = nulls.get(c.table) ?? { sum: 0, n: 0 };
      acc.sum += c.null_rate;
      acc.n += 1;
      nulls.set(c.table, acc);
    }
    return tables.data.tables
      .filter(t => !prefix || t.table.startsWith(prefix))
      .map(t => {
        const acc = nulls.get(t.table);
        return { ...t, name: prefix ? t.table.slice(prefix.length) : t.table, avgNull: acc?.n ? acc.sum / acc.n : null };
      });
  }, [tables, schema]);
  const lastProfiled = tableRows.reduce<string | null>((a, t) => (!a || t.computed_at > a ? t.computed_at : a), null);

  // A connection's own entry for a metric beats the global one of the same name.
  const governed = useMemo(() => {
    if (metrics.state !== "ready") return [];
    const byName = new Map<string, Metric>();
    for (const m of metrics.data) {
      const scope = m.connection ?? "*";
      if (scope !== "*" && scope !== connectionId) continue;
      const prev = byName.get(m.name);
      if (!prev || ((prev.connection ?? "*") === "*" && scope !== "*")) byName.set(m.name, m);
    }
    return [...byName.values()];
  }, [metrics, connectionId]);
  const allGlobal = governed.length > 0 && governed.every(m => (m.connection ?? "*") === "*");

  const statusCols = findings.state === "ready" ? Object.entries(findings.data.lifecycle_maps ?? {}) : [];
  const blanks = findings.state === "ready"
    ? Object.entries(findings.data.null_meanings ?? {}).filter(([, v]) => v.meaning !== "not_applicable" && v.meaning !== "unknown")
    : [];

  const stripMeta = [
    generatedAt ? `business profile inferred ${relTime(generatedAt)} ago` : "",
    lastProfiled ? `tables profiled ${relTime(lastProfiled)} ago` : "",
  ].filter(Boolean).join(" · ");

  return (
    <div className="aug-profile">
      <div className="aug-profile-main">
        <div className="aug-brief-strip">
          <span className="aug-brief-eyebrow">Profile</span>
          {stripMeta && <span className="aug-brief-meta">{stripMeta}</span>}
          {canvasId && <span className="aug-brief-meta aug-profile-strip-end">connection-wide — a canvas does not narrow the profile</span>}
        </div>

        <Section>
          <div className="aug-brief-eyebrow-row">
            <span className="aug-brief-eyebrow">What this business is · {corrected ? "inferred, then corrected" : confirmed ? "inferred · org settings agree" : "inferred"}</span>
          </div>
          {profile.state === "loading" ? (
            <SkeletonRows rows={3} />
          ) : profile.state === "failed" ? (
            <p className="aug-brief-note">The business profile could not be read.</p>
          ) : !p ? (
            <p className="aug-brief-note">
              No business profile has been inferred for this {schema ? "schema" : "connection"} yet — the explorer infers one when it runs.
            </p>
          ) : (
            <>
              <p className="aug-profile-prose">{p.summary}</p>
              {facts.length > 0 && (
                <div className="aug-profile-facts">
                  {facts.map(f => <FactChip key={f.key} mark={f.mark} title={f.title}>{f.text}</FactChip>)}
                </div>
              )}
              {p.evidence && (
                <p className="aug-profile-why">
                  Why Aughor thinks so: {Array.isArray(p.evidence) ? p.evidence.join(" ") : p.evidence}
                </p>
              )}
            </>
          )}
        </Section>

        <Section>
          <div className="aug-brief-head">
            <span className="aug-brief-eyebrow">Data profile · by table</span>
            <span className="aug-brief-meta">rows · grain · latest record · null pressure · when profiled</span>
          </div>
          {tables.state === "loading" ? (
            <SkeletonRows rows={6} />
          ) : tables.state === "failed" ? (
            <p className="aug-brief-note">The table profile could not be read.</p>
          ) : tableRows.length === 0 ? (
            <p className="aug-brief-note">
              No table profile yet — tables are profiled when the connection is first read, and again after its schema changes.
            </p>
          ) : (
            <>
              <div className="aug-moves-wrap">
                <table className="aug-dt aug-profile-table">
                  <thead>
                    <tr>
                      <th>table</th>
                      <th>grain</th>
                      <th className="num">rows</th>
                      <th className="num">latest record</th>
                      <th className="num">avg null</th>
                      <th className="num">profiled</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map(t => (
                      <tr key={t.table}>
                        <td className="aug-profile-tname">{t.name}</td>
                        <td>
                          {t.grain_column ? (
                            <>
                              {t.grain_column}
                              {t.grain_verified
                                ? <span className="aug-moves-good" title="The profiler verified this key"> ✓</span>
                                : <span className="aug-profile-dim"> · unverified</span>}
                            </>
                          ) : <span className="aug-profile-dim">—</span>}
                        </td>
                        <td className="num">{formatCount(t.row_count)}</td>
                        <td className="num" title={t.primary_timestamp ? `the latest ${t.primary_timestamp}` : undefined}>
                          {t.date_range?.[1] ? t.date_range[1].slice(0, 10) : <span className="aug-profile-dim">no timestamp</span>}
                        </td>
                        <td className="num">{t.avgNull == null ? "—" : pct(t.avgNull, 1)}</td>
                        <td className="num aug-profile-dim" title={formatTimestamp(t.computed_at)}>{relTime(t.computed_at)} ago</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="aug-profile-foot">
                Grain is the key column the profiler checked — ✓ where it verified it. Null pressure is the average null rate
                across a table&apos;s columns. None of these figures records a human decision.
              </p>
            </>
          )}
        </Section>

        <Section>
          <div className="aug-brief-head">
            <span className="aug-brief-eyebrow">What a blank means · by column</span>
            <span className="aug-brief-meta">a null the explorer could explain, and the rule behind it</span>
          </div>
          {findings.state === "loading" ? (
            <SkeletonRows rows={3} />
          ) : findings.state === "failed" ? (
            <p className="aug-brief-note">The explorer&apos;s findings could not be read.</p>
          ) : blanks.length === 0 ? (
            <p className="aug-brief-note">The explorer has not named what a blank means in any column yet.</p>
          ) : (
            <div className="aug-moves-wrap">
              <table className="aug-dt aug-profile-table">
                <thead>
                  <tr>
                    <th>column</th>
                    <th>a blank means</th>
                    <th>rule</th>
                    <th className="num">null rate</th>
                  </tr>
                </thead>
                <tbody>
                  {blanks.map(([key, nm]) => {
                    const [table, column] = key.split(":");
                    return (
                      <tr key={key}>
                        <td className="aug-profile-tname">{table}.{column}</td>
                        <td className={nm.meaning === "missing" ? "aug-profile-gap" : undefined}>{BLANK[nm.meaning] ?? nm.meaning}</td>
                        <td className="aug-profile-rule" title={nm.business_rule ?? undefined}>{nm.business_rule ?? "—"}</td>
                        <td className="num">{nm.null_rate == null ? "—" : pct(nm.null_rate, 1)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </div>

      <aside className="aug-profile-rail" aria-label="Governed metrics and status columns">
        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Governed metrics</span>
          <span className="aug-brief-meta">
            {metrics.state === "ready" ? `${formatCount(governed.length)}${allGlobal ? " · global" : ""}` : ""}
          </span>
        </div>
        <div className="aug-profile-block">
          {metrics.state === "loading" ? (
            <SkeletonRows rows={2} />
          ) : metrics.state === "failed" ? (
            <p className="aug-brief-note">The metrics could not be read.</p>
          ) : governed.length === 0 ? (
            <p className="aug-brief-note">No governed metric applies to this connection.</p>
          ) : governed.map(m => (
            <div key={m.name} className="aug-profile-metric"
              title={(m.connection ?? "*") === "*" ? "Applies to every connection" : undefined}>
              <div className="aug-profile-metric-head">
                <span className="aug-profile-metric-name">{m.name}</span>
                <span className="aug-profile-metric-v">v{m.version ?? 0}</span>
                <span className="aug-profile-metric-state">{metricState(m.status)}</span>
              </div>
              <span className="aug-profile-formula">{m.sql}</span>
            </div>
          ))}
        </div>

        <div className="aug-profile-rail-head">
          <span className="aug-brief-eyebrow">Status columns</span>
          <span className="aug-brief-meta">{findings.state === "ready" ? countNoun(statusCols.length, "mapped", "mapped") : ""}</span>
        </div>
        <div className="aug-profile-block">
          {findings.state === "loading" ? (
            <SkeletonRows rows={3} />
          ) : findings.state === "failed" ? (
            <p className="aug-brief-note">The explorer&apos;s findings could not be read.</p>
          ) : statusCols.length === 0 ? (
            <p className="aug-brief-note">No status column has been mapped yet.</p>
          ) : statusCols.map(([table, lc]) => {
            const terminal = lc.terminal_states ?? [];
            const active = lc.active_states ?? [];
            const transitions = lc.transitions ?? [];
            return (
              <div key={table} className="aug-profile-lc">
                <span className="aug-profile-lc-name">{table}.{lc.status_column}</span>
                <div className="aug-profile-states">
                  {(lc.states ?? []).map(st => (
                    <span key={st}
                      className={`aug-profile-state${terminal.includes(st) ? " aug-profile-state-terminal" : ""}`}
                      title={terminal.includes(st) ? "terminal" : active.includes(st) ? "active" : undefined}>
                      {st}
                    </span>
                  ))}
                </div>
                <span className="aug-profile-lc-note">
                  {transitions.length > 0
                    ? `${countNoun(transitions.length, "transition")} observed between these values`
                    : "no transitions recorded, so no order is claimed"}
                </span>
              </div>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
