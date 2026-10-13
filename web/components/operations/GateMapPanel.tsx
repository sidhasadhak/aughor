"use client";

/**
 * Security & Audit ▸ Gate map and Policies — "see every door in and out and what guards it" (the 2027 study §V,
 * screen 12), redone to `aughor-v2/CLARITY.md` (2026-10-13).
 *
 * The gate map is a map, so it opens on the picture: the places in the code that send a statement, the doors they go
 * through and the warehouse they reach; and the messages leaving the platform, through the departure gate's laws in the
 * order they run. Under it, how each place meets the engine's dialect as bars, and the places nothing guards with the
 * reason each is still there. It used to be four tables and three notes; every figure, note and law is still here —
 * the laws' long sentences behind each law's name (hover), Copy · CSV on each part.
 *
 * Policies are a ledger of rules, read like a page: each rule as a sentence, its facts as chips, its one button on its
 * row — what an agent may do, what may be spent, the groups, identity, and the ledger's way out — including what is
 * recorded and not yet enforced.
 */
import type { CSSProperties, ReactNode } from "react";

import { CARD, Card, Chip, Empty, HBars, Label, MUTED, NUM, ONE_LINE, Page, ROW, RULE } from "@/components/clarity/kit";
import { Gate, useLoad } from "@/components/record/kit";
import { TableActions } from "@/components/TableActions";
import { Button } from "@/components/ui/button";
import { getApiBase } from "@/lib/config";
import { compactNumber, countNoun, formatCount, formatTableNumber, MONTHS_SHORT } from "@/lib/format";
import { withUniqueKeys } from "@/lib/listKeys";
import { keyToWords } from "@/lib/names";
import { whoLabel } from "@/lib/record";

interface Site { key: string; path: string; function: string; door: string; label: string; dialect: string; author: string; note: string }
interface GateMap {
  statements: {
    present: boolean; sites: number; note: string;
    by_dialect: { dialect: string; sites: number; means: string }[];
    by_door: { door: string; sites: number; uses: number; last_used: string }[];
    counted_since?: string | null; uses_note?: string;
    unguarded: Site[];
  };
  departures: {
    over: number; note: string;
    laws: { guard: string; label: string; law: string; sentence: string; meaning: string; passed: number; held: number; asked: number; last_held: string }[];
  };
}
type Door = GateMap["statements"]["by_door"][number];
type Law = GateMap["departures"]["laws"][number];

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`);
  if (!res.ok) throw new Error(`${path} could not be read (${res.status})`);
  return res.json();
}

/** "13 Oct" from an ISO day or timestamp; the day as written when it is not one. */
function dayOf(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${Number(m[3])} ${MONTHS_SHORT[Number(m[2]) - 1]}` : iso;
}

// ── the picture's parts ──────────────────────────────────────────────────────────────────

/** The height of one row of a lane: every node in a column is one row tall, so a link lands on its middle. */
const ROW_H = 46;
const LAW_H = 40;
const LINE = "1px solid var(--t4)";
const NODE: CSSProperties = {
  background: "var(--bg-3)", border: "1px solid var(--b1)", borderRadius: "var(--r2)", padding: "4px 9px",
  minWidth: 0, alignSelf: "center",
};

/** A box in the picture: its name, one muted line under it. */
function Node({ name, sub, title, style, testId }: {
  name: ReactNode; sub?: ReactNode; title?: string; style?: CSSProperties; testId?: string;
}) {
  return (
    <div title={title} data-testid={testId} style={{ ...NODE, ...style }}>
      <div className="aug-fs-sm" style={{ ...ONE_LINE, color: "var(--t1)", fontWeight: 500 }}>{name}</div>
      {sub != null && <div className="aug-fs-xs" style={{ ...ONE_LINE, ...MUTED, ...NUM }}>{sub}</div>}
    </div>
  );
}

/** An arrowhead pointing right, its tip at `right: 0` of the run it ends. */
function Head({ top }: { top: string }) {
  return (
    <i style={{ position: "absolute", right: 0, top, transform: "translateY(-50%)", width: 0, height: 0,
      borderTop: "4px solid transparent", borderBottom: "4px solid transparent", borderLeft: "6px solid var(--t4)" }} />
  );
}

/**
 * The links between one box and a column of `n` rows, straight and turning only at a right angle (CLARITY §3, the user
 * 2026-10-13 — the step link `OntologyCanvas` draws): each leaves its box level, turns upright halfway across the gap,
 * and arrives level on the middle of its row. `out` fans from the one box on the left to every row on the right; `in`
 * gathers every row on the left into the one box on the right.
 */
function Links({ n, dir, column }: { n: number; dir: "out" | "in"; column: number }) {
  const mid = (i: number) => ((i + 0.5) / n) * 100;
  const rows = Array.from({ length: n }, (_, i) => i);
  const out = dir === "out";
  return (
    <div aria-hidden style={{ position: "relative", gridColumn: column, gridRow: `1 / span ${n}` }}>
      <i style={{ position: "absolute", top: "50%", left: out ? 0 : undefined, right: out ? undefined : 0, width: "50%", borderTop: LINE }} />
      {n > 1 && <i style={{ position: "absolute", left: "50%", top: `${mid(0)}%`, height: `${mid(n - 1) - mid(0)}%`, borderLeft: LINE }} />}
      {rows.map(i => (
        <i key={i} style={{ position: "absolute", top: `${mid(i)}%`, left: out ? undefined : 0, right: out ? 0 : undefined,
          width: "50%", borderTop: LINE }} />
      ))}
      {out ? rows.map(i => <Head key={i} top={`${mid(i)}%`} />) : <Head top="50%" />}
    </div>
  );
}

/** A single link from the middle of one box to one row of the next column, square like the fans. */
function Link({ n, column, from, to }: { n: number; column: number; from: number | "mid"; to: number | "mid" }) {
  const y = (r: number | "mid") => (r === "mid" ? 50 : ((r + 0.5) / n) * 100);
  const a = y(from), b = y(to);
  return (
    <div aria-hidden style={{ position: "relative", gridColumn: column, gridRow: `1 / span ${n}` }}>
      <i style={{ position: "absolute", top: `${a}%`, left: 0, width: "50%", borderTop: LINE }} />
      {a !== b && <i style={{ position: "absolute", left: "50%", top: `${Math.min(a, b)}%`, height: `${Math.abs(a - b)}%`, borderLeft: LINE }} />}
      <i style={{ position: "absolute", top: `${b}%`, right: 0, width: "50%", borderTop: LINE }} />
      <Head top={`${b}%`} />
    </div>
  );
}

// ── the gate map ─────────────────────────────────────────────────────────────────────────

const dialectWords = (d: string) => (d === "none" ? "none — undeclared" : keyToWords(d));

function doorSub(d: Door, since: string | null | undefined): string {
  const places = countNoun(d.sites, "place");
  if (!d.uses) return `${places} · not used${since ? ` since ${dayOf(since)}` : ""}`;
  return `${places} · ${compactNumber(d.uses)} uses${d.last_used ? ` · last ${dayOf(d.last_used)}` : ""}`;
}

/** Statements in: the places in the code → the door each goes through → the warehouse. */
function StatementsIn({ s }: { s: GateMap["statements"] }) {
  const doors = s.by_door;
  const n = Math.max(1, doors.length);
  return (
    <div data-testid="gate-in-flow" style={{ display: "grid", gridTemplateRows: `repeat(${n}, ${ROW_H}px)`,
      gridTemplateColumns: "minmax(110px, 160px) 44px minmax(190px, 1fr) 44px minmax(96px, 130px)" }}>
      <Node name={countNoun(s.sites, "place") + " in the code"} title={`${s.note}.`}
        sub={s.unguarded.length ? `${formatCount(s.unguarded.length)} with no guard` : "each one guarded"}
        style={{ gridColumn: 1, gridRow: `1 / span ${n}` }} testId="gate-in-places" />
      <Links n={n} dir="out" column={2} />
      {doors.map((d, i) => (
        <Node key={d.door} name={keyToWords(d.door)} sub={doorSub(d, s.counted_since)} testId="gate-door"
          title={`${keyToWords(d.door)}: ${countNoun(d.sites, "place")} in the code call it; ${formatCount(d.uses)} uses`
            + `${d.last_used ? `, the last on ${dayOf(d.last_used)}` : ""}.`}
          style={{ gridColumn: 3, gridRow: i + 1, ...(d.uses ? {} : { background: "transparent" }) }} />
      ))}
      <Links n={n} dir="in" column={4} />
      <Node name="The warehouse" sub="every connection" style={{ gridColumn: 5, gridRow: `1 / span ${n}` }} />
    </div>
  );
}

/** What a law did over the messages counted, after its held count (which the row sets apart when there is one). */
function lawSub(l: Law): string {
  if (!l.passed && !l.held && !l.asked) return "met none";
  return [
    l.held ? "" : "none held",
    l.asked ? `${formatCount(l.asked)} asked` : "",
    `${formatCount(l.passed)} passed`,
  ].filter(Boolean).join(" · ").replace(/^/, l.held ? " · " : "");
}

/** Messages out: what leaves the platform → each law of the departure gate, in the order they run → out. */
function MessagesOut({ d }: { d: GateMap["departures"] }) {
  const laws = d.laws;
  const n = Math.max(1, laws.length);
  return (
    <div data-testid="gate-out-flow" style={{ display: "grid", gridTemplateRows: `repeat(${n}, ${LAW_H}px)`,
      gridTemplateColumns: "minmax(96px, 140px) 40px minmax(200px, 1fr) 40px minmax(96px, 130px)" }}>
      <Node name="Leaving" sub={`newest ${formatCount(d.over)} checked`} title={`${d.note}.`}
        style={{ gridColumn: 1, gridRow: `1 / span ${n}` }} />
      <Link n={n} column={2} from="mid" to={0} />
      {/* The gate: its laws as one chain, run top to bottom — a rail with a mark at each law. */}
      <div aria-hidden style={{ gridColumn: 3, gridRow: `1 / span ${n}`, position: "relative", zIndex: 1, pointerEvents: "none" }}>
        <i style={{ position: "absolute", left: 13, top: `${(0.5 / n) * 100}%`, bottom: `${(0.5 / n) * 100}%`, borderLeft: LINE }} />
      </div>
      {laws.map((l, i) => {
        const met = l.passed + l.held + l.asked > 0;
        return (
          <div key={l.guard} data-testid="gate-law" title={`${l.meaning}${l.sentence ? `\n\nThe law: ${l.sentence}` : ""}`}
            style={{ gridColumn: 3, gridRow: i + 1, display: "grid", gridTemplateColumns: "28px minmax(0, 1fr)",
              alignItems: "center", columnGap: 4, minWidth: 0, paddingRight: 9,
              borderLeft: "1px solid var(--b1)", borderRight: "1px solid var(--b1)", background: "var(--bg-3)",
              ...(i === 0 ? { borderTop: "1px solid var(--b1)", borderRadius: "var(--r2) var(--r2) 0 0" } : {}),
              ...(i === n - 1 ? { borderBottom: "1px solid var(--b1)", borderRadius: "0 0 var(--r2) var(--r2)" } : {}) }}>
            <span aria-hidden style={{ justifySelf: "center", position: "relative", zIndex: 2, width: 7, height: 7, borderRadius: "var(--r-pill)",
              background: met ? "var(--t3)" : "var(--bg-3)", border: "1px solid var(--t3)" }} />
            <span style={{ minWidth: 0 }}>
              <span className="aug-fs-sm" style={{ ...ONE_LINE, display: "block", color: met ? "var(--t1)" : "var(--t3)", fontWeight: 500 }}>
                {l.label}{l.law && <span className="aug-fs-xs" style={{ ...MUTED, fontWeight: 400 }}> · {l.law}</span>}
              </span>
              <span className="aug-fs-xs" style={{ ...ONE_LINE, ...NUM, display: "block", ...MUTED }}>
                {l.held > 0 ? <span style={{ color: "var(--t1)" }}>{formatCount(l.held)} held</span> : null}
                {lawSub(l)}{l.last_held ? ` · last ${dayOf(l.last_held)}` : ""}
              </span>
            </span>
          </div>
        );
      })}
      <Link n={n} column={4} from={n - 1} to="mid" />
      <Node name="Out" sub="if no law holds it" title="A message leaves only when no law held it; a law that asks waits for the owner's answer."
        style={{ gridColumn: 5, gridRow: `1 / span ${n}` }} />
    </div>
  );
}

export function GateMapView() {
  const load = useLoad(() => get<GateMap>("/governance/gate-map"), []);
  return (
    <Page testId="gate-map">
      <Gate load={load} what="the gate map">
        {g => {
          const s = g.statements;
          return (
            <>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "stretch" }}>
                <section aria-label="Statements in" data-testid="gate-in" style={{ ...CARD, flex: "1.15 1 560px" }}>
                  <Label right={s.present && <>
                    {s.uses_note && <Chip title={`${s.uses_note}.`}>{s.counted_since ? `uses since ${dayOf(s.counted_since)}` : "uses not counted yet"}</Chip>}
                    <TableActions name="statement-doors" read={() => ({
                      columns: ["Door", "Places", "Uses", "Last used"],
                      rows: s.by_door.map(d => [keyToWords(d.door), d.sites, d.uses, d.last_used ? d.last_used.slice(0, 10) : ""]),
                    })} />
                  </>}>Statements in</Label>
                  {s.present ? <StatementsIn s={s} /> : <Empty>{s.note}.</Empty>}
                </section>
                <section aria-label="Messages out" data-testid="gate-out" style={{ ...CARD, flex: "1 1 520px" }}>
                  <Label right={g.departures.laws.length > 0 && (
                    <TableActions name="departure-laws" read={() => ({
                      columns: ["Law", "Number", "What a hold means", "The law", "Passed", "Held", "Asked", "Last held"],
                      rows: g.departures.laws.map(l => [l.label, l.law, l.meaning, l.sentence, l.passed, l.held, l.asked,
                        l.last_held ? l.last_held.slice(0, 10) : ""]),
                    })} />
                  )}>Messages out · the departure gate</Label>
                  {g.departures.laws.length ? <MessagesOut d={g.departures} /> : <Empty>The departure gate declares no law.</Empty>}
                </section>
              </div>

              {s.present && (
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-start" }}>
                  <Card label="How each place meets the engine's dialect" testId="gate-dialects" style={{ flex: "1.3 1 460px" }}
                    right={s.by_dialect.length > 0 && (
                      <TableActions name="statement-doors-by-dialect" read={() => ({
                        columns: ["How the dialect is handled", "Places", "What that means"],
                        rows: s.by_dialect.map(r => [r.dialect, r.sites, r.means]),
                      })} />
                    )}>
                    {s.by_dialect.length === 0 ? <Empty>No place is recorded.</Empty> : (
                      <HBars bars={s.by_dialect.map(r => ({
                        key: r.dialect, name: dialectWords(r.dialect), meta: r.means, value: r.sites, shown: formatCount(r.sites),
                        tip: `${dialectWords(r.dialect)}: ${countNoun(r.sites, "place")} — ${r.means}`,
                      }))} />
                    )}
                  </Card>
                  <Card label="Places nothing guards" testId="gate-unguarded" style={{ flex: "1 1 360px" }}
                    right={<span style={NUM}>{formatCount(s.unguarded.length)}</span>}>
                    {s.unguarded.length === 0 ? (
                      <Empty>Every statement declares its dialect, is written for its engine, or is rendered for it.</Empty>
                    ) : s.unguarded.map((site, i) => (
                      <div key={site.key} data-testid="gate-unguarded-site" style={{ padding: "7px 2px", ...(i ? RULE : {}) }}>
                        <div className="aug-fs-sm" style={{ color: "var(--t1)" }}>{site.note || "no reason recorded"}</div>
                        <div className="aug-fs-xs" title={site.key} style={{ ...MUTED, ...ONE_LINE, marginTop: 2 }}>
                          <span className="aug-mono">{site.path}</span> · in {site.function} · written by{" "}
                          {site.author === "person" ? "a person" : site.author === "model" ? "a model" : `the ${site.author}`}
                        </div>
                      </div>
                    ))}
                  </Card>
                </div>
              )}
            </>
          );
        }}
      </Gate>
    </Page>
  );
}

// ── policies, groups, identity, the audit's way out ──────────────────────────────────────

interface AgentPolicy {
  effective: { level: string; connections: string[] | null; tools: string[] | null; set_by: string; updated_at: string; source: string; narrowed_by: string[] };
  levels: string[];
}
interface Caps { caps: { scope: string; subject: string; metric: string; limit: number; window_hours: number; action: string }[] }
interface Role { name: string; label: string; description: string; permissions: string[] }
interface Assignment { user_id?: string; principal?: string; role: string; [k: string]: unknown }
interface Me { user_id: string | null; org_id: string; roles: string[] }

const LEVEL_SENTENCE: Record<string, string> = {
  read: "An agent may look things up, and nothing else.",
  run: "An agent may look things up, start work and book an entry with its warrant. It may not change anything outside the conversation.",
  act: "An agent may look things up, start work, book entries and change something outside the conversation.",
};

const METRIC_WORDS: Record<string, string> = { calls: "model calls", total_tokens: "tokens", cost_usd: "US dollars" };

const GROUPS_WAIT = "A group's grants are read when a caller is identified. With identity off, every caller holds the owner's"
  + " role, so nothing here narrows what anyone sees yet.";

/** One rule of the page: its name at the left, the rule as a sentence with its facts, its one button at the right. */
function Rule({ name, action, first = false, children }: { name: string; action?: ReactNode; first?: boolean; children: ReactNode }) {
  return (
    <div role="group" aria-label={name} data-testid="policy-rule"
      style={{ display: "grid", gridTemplateColumns: "minmax(90px, 150px) minmax(0, 1fr) auto", gap: "4px 18px",
        alignItems: "start", padding: "12px 2px", ...(first ? {} : RULE) }}>
      <div className="aug-fs-xs" style={{ ...MUTED, textTransform: "uppercase", letterSpacing: ".06em", paddingTop: 3 }}>{name}</div>
      <div style={{ minWidth: 0 }}>{children}</div>
      <div style={{ ...ROW, flexWrap: "nowrap" }}>{action}</div>
    </div>
  );
}

const SENTENCE: CSSProperties = { color: "var(--t1)", lineHeight: 1.55 };
const FACTS: CSSProperties = { ...ROW, gap: 6, marginTop: 6 };

export function PoliciesView({ onOpenSettings, onOpenSpend }: {
  onOpenSettings: () => void; onOpenSpend: () => void;
}) {
  const policy = useLoad(() => get<AgentPolicy>("/org-settings/agent-policy"), []);
  const caps = useLoad(() => get<Caps>("/governance/caps"), []);
  const roles = useLoad(() => Promise.all([get<Role[]>("/rbac/roles"), get<Assignment[]>("/rbac/assignments")]), []);
  const me = useLoad(() => get<Me>("/rbac/me"), []);
  const identityOff = me.data !== null && !me.data.user_id;
  return (
    <Page testId="policies">
      <div className="aug-fs-ui" style={{ color: "var(--t2)" }}>The rules agents and people work under here, each read back as a sentence.</div>
      <section aria-label="Policies" style={CARD}>
        <Rule name="Agents" first action={<Button size="xs" variant="ghost" onClick={onOpenSettings}>Change it</Button>}>
          <Gate load={policy} what="the agent policy">
            {p => {
              const e = p.effective;
              return (
                <>
                  <div className="aug-fs-ui" style={SENTENCE}>{LEVEL_SENTENCE[e.level] ?? `Agents are held at "${e.level}".`}</div>
                  <div style={FACTS}>
                    <Chip title={`The level an agent is held at: ${p.levels.join(" · ")}`}>{e.level}</Chip>
                    <Chip>{e.connections ? `on ${countNoun(e.connections.length, "connection")} only` : "every connection"}</Chip>
                    <Chip>{e.tools ? `${countNoun(e.tools.length, "tool")} only` : "every tool its level allows"}</Chip>
                    <Chip>{e.source === "default" ? "the default · nobody has set it"
                      : `set by ${whoLabel(e.set_by)}${e.updated_at ? ` · ${dayOf(e.updated_at)}` : ""}`}</Chip>
                    {e.narrowed_by.length > 0 && <Chip title="The server's environment narrows the saved policy">{`narrowed by ${e.narrowed_by.join(", ")}`}</Chip>}
                  </div>
                </>
              );
            }}
          </Gate>
        </Rule>

        <Rule name="Spending" action={<Button size="xs" variant="ghost" onClick={onOpenSpend}>Spend</Button>}>
          <Gate load={caps} what="the spend caps">
            {c => c.caps.length === 0 ? (
              <div className="aug-fs-ui" style={{ ...SENTENCE, ...ROW }}>
                <Chip tone="amber" testId="policy-no-cap" title="A cap reads back here as a sentence once one is written on the Spend page.">no cap</Chip>
                Nothing alerts or blocks on usage.
              </div>
            ) : (
              <>{withUniqueKeys(c.caps, cap => `${cap.scope}:${cap.subject}:${cap.metric}:${cap.window_hours}`).map(([key, cap]) => (
                <div className="aug-fs-ui" key={key} style={SENTENCE}>
                  {cap.action === "block" ? "Block" : "Alert"} when {cap.subject === "*" ? `any ${cap.scope === "org" ? "organisation" : cap.scope}` : `${cap.scope} ${cap.subject}`} uses
                  more than {formatTableNumber(cap.limit)} {METRIC_WORDS[cap.metric] ?? cap.metric} in {cap.window_hours} hours.
                </div>
              ))}</>
            )}
          </Gate>
        </Rule>

        <Rule name="Groups" action={<Button size="xs" variant="ghost" onClick={onOpenSettings}>Access</Button>}>
          <Gate load={roles} what="the groups">
            {([rs, as]) => (
              <>
                {withUniqueKeys(rs, r => r.name).map(([key, r]) => {
                  const members = as.filter(a => a.role === r.name).map(m => whoLabel(String(m.user_id ?? m.principal ?? "")));
                  return (
                    <div key={key} data-testid="policy-group" style={{ padding: "2px 0" }}>
                      <span className="aug-fs-ui" style={{ color: "var(--t1)", fontWeight: 500 }}>{r.label}</span>
                      <span className="aug-fs-ui" style={{ color: "var(--t2)" }}> — {r.description}</span>
                      <span className="aug-fs-xs" style={{ ...MUTED, marginLeft: 8 }} title={r.permissions.join(", ")}>
                        {members.length ? members.join(", ") : "nobody assigned"} · {countNoun(r.permissions.length, "permission")}
                      </span>
                    </div>
                  );
                })}
                {identityOff && (
                  <div style={FACTS}><Chip title={GROUPS_WAIT} testId="policy-groups-wait">narrow nothing while identity is off</Chip></div>
                )}
              </>
            )}
          </Gate>
        </Rule>

        <Rule name="Identity">
          <Gate load={me} what="who you are to the platform">
            {m => m.user_id ? (
              <div className="aug-fs-ui" style={SENTENCE}>You are {whoLabel(m.user_id)}, holding {m.roles.join(" and ")}.</div>
            ) : (
              <>
                <div className="aug-fs-ui" style={SENTENCE}>Off: nobody is asked who they are, and every caller is treated as the owner.</div>
                <div style={FACTS}>
                  <Chip title="Identity is turned on when the server starts — a restart, by design.">
                    <span className="aug-mono">AUGHOR_REQUIRE_IDENTITY=1</span> turns it on
                  </Chip>
                </div>
              </>
            )}
          </Gate>
        </Rule>

        <Rule name="The ledger"
          action={<a href={`${getApiBase()}/ledger/v1/export`} download="aughor-ledger.jsonl" className="aug-fs-sm"
            style={{ color: "var(--blue4)", whiteSpace: "nowrap" }}>Download</a>}>
          <div className="aug-fs-ui" style={SENTENCE}>
            Leaves as one file of JSON lines: every claim, decision, outcome, inquiry and mission as it stands.
          </div>
          <div className="aug-fs-xs" style={{ ...MUTED, marginTop: 4 }}>The governance events of every audit sink are in the Spend page&apos;s feed.</div>
        </Rule>
      </section>
    </Page>
  );
}
